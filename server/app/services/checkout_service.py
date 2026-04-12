"""Checkout business logic — port of VBA Barcode() / addmaterials() subs."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from flask import current_app
from sqlalchemy import func

from ..database import db
from ..models import Book, Loan, Patron, Transaction
from .validators import (
    ValidationError,
    validate_barcode,
    validate_card,
)


def _utcnow() -> datetime:
    """Return current UTC time as a naive datetime (SQLite-compatible)."""
    return datetime.now(UTC).replace(tzinfo=None)


# ── Stats cache ──────────────────────────────────────────────────────────────

_STATS_CACHE_TTL = 30  # seconds
_stats_cache: dict | None = None
_stats_cache_time: float = 0


def next_card_number() -> str:
    """Return the next sequential 14-digit library card number.

    Scans all existing card numbers numerically and returns max + 1,
    starting from ``10000000000001`` when no patrons exist yet.
    """
    base = 10_000_000_000_001
    rows = db.session.query(Patron.card_number).all()
    max_num = base - 1
    for (c,) in rows:
        try:
            n = int(c)
            if n > max_num:
                max_num = n
        except (ValueError, TypeError):
            continue
    return str(max_num + 1)


def get_or_create_patron(
    card: str,
    first_name: str | None = None,
    last_name: str | None = None,
    middle_name: str | None = None,
    birth_date: date | None = None,
    email: str | None = None,
    phone: str | None = None,
) -> Patron:
    """Look up a patron by card number, registering a new one if not found."""
    card = validate_card(card)
    patron = Patron.query.filter_by(card_number=card).first()
    if patron:
        return patron
    if not first_name or not first_name.strip():
        raise ValidationError("First name required for new patron registration")
    if not last_name or not last_name.strip():
        raise ValidationError("Last name required for new patron registration")
    if birth_date is None:
        raise ValidationError("Birth date required for new patron registration")
    patron = Patron(
        card_number=card,
        first_name=first_name.strip().upper(),
        last_name=last_name.strip().upper(),
        middle_name=middle_name.strip().upper() if middle_name and middle_name.strip() else None,
        birth_date=birth_date,
        email=email,
        phone=phone,
    )
    db.session.add(patron)
    db.session.commit()
    current_app.logger.info("Registered new patron %s", patron.masked_card)
    return patron


def add_book_to_catalog(
    barcode: str,
    title: str | None = None,
    author: str | None = None,
    category: str = "book",
) -> Book:
    """Add a new item to the catalog without checking it out."""
    barcode = validate_barcode(barcode)
    if Book.query.filter_by(barcode=barcode).first():
        raise ValidationError(f"Item {barcode} is already in the catalog")
    book = Book(
        barcode=barcode,
        title=title.strip() if title and title.strip() else None,
        author=author.strip() if author and author.strip() else None,
        category=category or "book",
    )
    db.session.add(book)
    db.session.commit()
    current_app.logger.info("Added to catalog: %s", barcode)
    return book


def overdue_items() -> list[dict]:
    """Return all currently overdue loans with patron and book details."""
    now = _utcnow()
    rows = (
        Loan.query.filter(
            Loan.returned_at.is_(None),
            Loan.due_date < now,
        )
        .join(Patron, Loan.patron_id == Patron.id)
        .join(Book, Loan.book_id == Book.id)
        .order_by(Loan.due_date.asc())
        .all()
    )
    result = []
    for loan in rows:
        days = (now - loan.due_date).days
        result.append(
            {
                "patron_name": loan.patron.name,
                "card_number": loan.patron.card_number,
                "card_masked": loan.patron.masked_card,
                "book_title": loan.book.title or "(untitled)",
                "barcode": loan.book.barcode,
                "category": loan.book.category,
                "checked_out_at": loan.checked_out_at.isoformat(),
                "due_date": loan.due_date.isoformat(),
                "days_overdue": days,
            }
        )
    return result


def book_details(barcode: str) -> dict:
    """Return details about a book including its current loan status."""
    barcode = validate_barcode(barcode)
    book = Book.query.filter_by(barcode=barcode).first()
    if not book:
        raise ValidationError(f"Unknown item {barcode}")

    active_loan = Loan.query.filter_by(book_id=book.id, returned_at=None).first()
    result = book.to_dict()
    result["checked_out"] = active_loan is not None
    if active_loan:
        result["checked_out_to"] = active_loan.patron.name
        result["checked_out_card"] = active_loan.patron.card_number
        result["due_date"] = active_loan.due_date.isoformat() if active_loan.due_date else None
    return result


def get_or_create_book(barcode: str, title: str | None = None, category: str = "book") -> Book:
    """Look up an item by barcode, creating a new record if not found."""
    book = Book.query.filter_by(barcode=barcode).first()
    if book:
        if title and not book.title:
            book.title = title
        return book
    book = Book(barcode=barcode, title=title, category=category)
    db.session.add(book)
    db.session.flush()
    return book


def checkout_item(
    card: str,
    barcode: str,
    loan_days: int = 14,
    category: str = "book",
    title: str | None = None,
) -> Loan:
    """Check out a single item to a patron.

    Creates a Loan record and a corresponding Transaction audit entry.
    """
    patron = Patron.query.filter_by(card_number=validate_card(card)).first()
    if not patron:
        raise ValidationError("Patron not found — register first")
    if not patron.is_active:
        raise ValidationError("Patron account is archived — reactivate before checking out")

    barcode = validate_barcode(barcode)

    book = get_or_create_book(barcode, title=title, category=category)
    if not book.is_active:
        raise ValidationError(f"Item {barcode} is archived — reactivate before checking out")
    existing = Loan.query.filter_by(book_id=book.id, returned_at=None).first()
    if existing:
        raise ValidationError(f"Item {barcode} is already checked out")

    now = _utcnow()
    due = now + timedelta(days=loan_days)
    loan = Loan(
        patron_id=patron.id,
        book_id=book.id,
        loan_days=loan_days,
        checked_out_at=now,
        due_date=due,
    )
    db.session.add(loan)
    db.session.flush()

    txn = Transaction(loan_id=loan.id, action="checkout", created_at=now)
    db.session.add(txn)
    db.session.commit()

    current_app.logger.info(
        "Checkout: patron=%s book=%s loan_days=%d", patron.masked_card, barcode, loan_days
    )
    return loan


def return_item(barcode: str) -> Loan:
    """Mark the active loan for an item as returned.

    Sets returned_at on the Loan and logs a Transaction audit entry.
    """
    barcode = validate_barcode(barcode)
    book = Book.query.filter_by(barcode=barcode).first()
    if not book:
        raise ValidationError(f"Unknown item {barcode}")

    active = Loan.query.filter_by(book_id=book.id, returned_at=None).first()
    if not active:
        raise ValidationError(f"Item {barcode} is not currently checked out")

    now = _utcnow()
    active.returned_at = now

    txn = Transaction(loan_id=active.id, action="return", created_at=now)
    db.session.add(txn)
    db.session.commit()

    current_app.logger.info("Return: book=%s", barcode)
    return active


def renew_item(barcode: str, loan_days: int = 14) -> Loan:
    """Extend the due date of an active loan from today.

    Updates the Loan's due_date and logs a Transaction audit entry.
    """
    barcode = validate_barcode(barcode)
    book = Book.query.filter_by(barcode=barcode).first()
    if not book:
        raise ValidationError(f"Unknown item {barcode}")
    active = Loan.query.filter_by(book_id=book.id, returned_at=None).first()
    if not active:
        raise ValidationError(f"Item {barcode} is not currently checked out")

    now = _utcnow()
    active.due_date = now + timedelta(days=loan_days)
    active.loan_days = loan_days

    txn = Transaction(loan_id=active.id, action="renew", created_at=now)
    db.session.add(txn)
    db.session.commit()

    current_app.logger.info("Renew: book=%s loan_days=%d", barcode, loan_days)
    return active


def library_stats(*, force: bool = False) -> dict:
    """Aggregate library-wide statistics for the dashboard.

    Results are cached for ``_STATS_CACHE_TTL`` seconds.  Pass
    ``force=True`` to bypass the cache (e.g. when the user clicks Refresh).
    """
    global _stats_cache, _stats_cache_time  # noqa: PLW0603

    import time

    if (
        not force
        and _stats_cache is not None
        and (time.monotonic() - _stats_cache_time) < _STATS_CACHE_TTL
    ):
        return _stats_cache

    now = _utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    total_patrons = Patron.query.count()
    total_books = Book.query.count()

    active_checkouts = Loan.query.filter(Loan.returned_at.is_(None)).count()

    overdue_count = Loan.query.filter(
        Loan.returned_at.is_(None),
        Loan.due_date < now,
    ).count()

    total_checkout_events = Transaction.query.filter_by(action="checkout").count()

    checkouts_today = Transaction.query.filter(
        Transaction.action == "checkout",
        Transaction.created_at >= today_start,
    ).count()

    checkouts_this_week = Transaction.query.filter(
        Transaction.action == "checkout",
        Transaction.created_at >= week_start,
    ).count()

    by_category = (
        db.session.query(Book.category, func.count(Loan.id))
        .join(Loan, Loan.book_id == Book.id)
        .filter(Loan.returned_at.is_(None))
        .group_by(Book.category)
        .order_by(func.count(Loan.id).desc())
        .all()
    )

    top_books = (
        db.session.query(Book.title, Book.barcode, func.count(Loan.id).label("cnt"))
        .join(Loan, Loan.book_id == Book.id)
        .group_by(Book.id)
        .order_by(func.count(Loan.id).desc())
        .limit(5)
        .all()
    )

    result = {
        "total_patrons": total_patrons,
        "total_books": total_books,
        "active_checkouts": active_checkouts,
        "overdue_items": overdue_count,
        "total_checkout_events": total_checkout_events,
        "checkouts_today": checkouts_today,
        "checkouts_this_week": checkouts_this_week,
        "by_category": [{"category": c, "count": n} for c, n in by_category],
        "top_books": [
            {"title": t or barcode, "barcode": barcode, "checkouts": n}
            for t, barcode, n in top_books
        ],
        "generated_at": now.isoformat(),
    }

    _stats_cache = result
    _stats_cache_time = time.monotonic()

    return result


def search_patrons(query: str) -> list[Patron]:
    """Search patrons by first or last name (case-insensitive partial match)."""
    q = query.strip().upper()
    if not q:
        return []
    return (
        Patron.query.filter(
            db.or_(
                Patron.last_name.contains(q),
                Patron.first_name.contains(q),
            )
        )
        .limit(50)
        .all()
    )


def patron_summary(card: str) -> dict:
    """Build the dashboard summary card."""
    card = validate_card(card)
    patron = Patron.query.filter_by(card_number=card).first()
    if not patron:
        raise ValidationError("Patron not found")

    all_loans = Loan.query.filter_by(patron_id=patron.id).all()
    active = [ln for ln in all_loans if ln.is_active]
    late = [ln for ln in active if ln.is_late]

    # Build history from transactions, ordered newest first.
    # Includes loan-level events (via loan FK) and patron-level events (via patron FK).
    history = (
        Transaction.query.outerjoin(Loan, Transaction.loan_id == Loan.id)
        .filter(
            db.or_(
                Loan.patron_id == patron.id,
                Transaction.patron_id == patron.id,
            )
        )
        .order_by(Transaction.created_at.desc())
        .all()
    )

    return {
        "patron": patron.to_dict(),
        "account_age_days": (_utcnow() - patron.created_at).days,
        "total_checkouts": len(all_loans),
        "currently_out": len(active),
        "late_count": len(late),
        "active_items": [ln.to_dict() for ln in active],
        "history": [txn.to_dict() for txn in history],
    }


# ── Archive / Reactivate ────────────────────────────────────────────────────


def archive_patron(card: str) -> Patron:
    """Archive a patron account (soft-delete).

    All active loans must be returned first. Sets ``is_active = False``
    and logs an ``archive_patron`` transaction.
    """
    card = validate_card(card)
    patron = Patron.query.filter_by(card_number=card).first()
    if not patron:
        raise ValidationError("Patron not found")
    if not patron.is_active:
        raise ValidationError("Patron is already archived")

    active_loans = Loan.query.filter_by(patron_id=patron.id, returned_at=None).count()
    if active_loans:
        raise ValidationError(
            f"Cannot archive — patron has {active_loans} active loan(s). Return all items first."
        )

    patron.is_active = False
    txn = Transaction(patron_id=patron.id, action="archive_patron", created_at=_utcnow())
    db.session.add(txn)
    db.session.commit()
    current_app.logger.info("Archived patron %s", patron.masked_card)
    return patron


def reactivate_patron(card: str) -> Patron:
    """Reactivate a previously archived patron account."""
    card = validate_card(card)
    patron = Patron.query.filter_by(card_number=card).first()
    if not patron:
        raise ValidationError("Patron not found")
    if patron.is_active:
        raise ValidationError("Patron is already active")

    patron.is_active = True
    txn = Transaction(patron_id=patron.id, action="reactivate_patron", created_at=_utcnow())
    db.session.add(txn)
    db.session.commit()
    current_app.logger.info("Reactivated patron %s", patron.masked_card)
    return patron


def archive_book(barcode: str) -> Book:
    """Archive a book from the catalog (soft-delete).

    The book must not be currently checked out. Sets ``is_active = False``
    and logs an ``archive_book`` transaction.
    """
    barcode = validate_barcode(barcode)
    book = Book.query.filter_by(barcode=barcode).first()
    if not book:
        raise ValidationError(f"Unknown item {barcode}")
    if not book.is_active:
        raise ValidationError(f"Item {barcode} is already archived")

    active_loan = Loan.query.filter_by(book_id=book.id, returned_at=None).first()
    if active_loan:
        raise ValidationError(
            f"Cannot archive — item {barcode} is currently checked out. Return it first."
        )

    book.is_active = False
    txn = Transaction(book_id=book.id, action="archive_book", created_at=_utcnow())
    db.session.add(txn)
    db.session.commit()
    current_app.logger.info("Archived book %s", barcode)
    return book


def reactivate_book(barcode: str) -> Book:
    """Reactivate a previously archived book."""
    barcode = validate_barcode(barcode)
    book = Book.query.filter_by(barcode=barcode).first()
    if not book:
        raise ValidationError(f"Unknown item {barcode}")
    if book.is_active:
        raise ValidationError(f"Item {barcode} is already active")

    book.is_active = True
    txn = Transaction(book_id=book.id, action="reactivate_book", created_at=_utcnow())
    db.session.add(txn)
    db.session.commit()
    current_app.logger.info("Reactivated book %s", barcode)
    return book
