"""Checkout business logic — port of VBA Barcode() / addmaterials() subs."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from flask import current_app
from sqlalchemy import func

from ..database import db
from ..models import Book, Checkout, Patron
from .validators import (
    ValidationError,
    validate_barcode,
    validate_card,
)


def _utcnow() -> datetime:
    """Return current UTC time as a naive datetime (SQLite-compatible)."""
    return datetime.now(UTC).replace(tzinfo=None)


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
    """Look up a patron by card number, registering a new one if not found.

    Args:
        card: Raw library card number (validated internally).
        first_name: Required only when the patron does not yet exist.
        last_name: Required only when the patron does not yet exist.
        middle_name: Optional middle name.
        birth_date: Required only when the patron does not yet exist.
        email: Optional contact email address.
        phone: Optional contact phone number.

    Returns:
        The existing or newly-created :class:`~server.app.models.Patron`.

    Raises:
        ValidationError: If the card number is invalid, or if required fields
            are omitted for a new patron.
    """
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
    """Add a new item to the catalog without checking it out.

    Args:
        barcode: Raw ISBN or library barcode (validated internally).
        title: Optional item title.
        author: Optional author name.
        category: Item category (default ``"book"``).

    Returns:
        The newly-created :class:`~server.app.models.Book`.

    Raises:
        ValidationError: If the barcode is invalid or already exists.
    """
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
    """Return all currently overdue checkouts with patron and book details.

    Returns:
        List of dicts, each containing patron name, card info, book info,
        due date, and days overdue, ordered by most overdue first.
    """
    now = _utcnow()
    rows = (
        Checkout.query.filter(
            Checkout.action == "checkout",
            Checkout.returned_at.is_(None),
            Checkout.due_date < now,
        )
        .join(Patron, Checkout.patron_id == Patron.id)
        .join(Book, Checkout.book_id == Book.id)
        .order_by(Checkout.due_date.asc())
        .all()
    )
    result = []
    for co in rows:
        days = (now - co.due_date).days
        result.append(
            {
                "patron_name": co.patron.name,
                "card_number": co.patron.card_number,
                "card_masked": co.patron.masked_card,
                "book_title": co.book.title or "(untitled)",
                "barcode": co.book.barcode,
                "category": co.book.category,
                "checked_out_at": co.checked_out_at.isoformat(),
                "due_date": co.due_date.isoformat(),
                "days_overdue": days,
            }
        )
    return result


def get_or_create_book(barcode: str, title: str | None = None, category: str = "book") -> Book:
    """Look up an item by barcode, creating a new record if not found.

    If the book already exists but has no title, and a ``title`` is provided,
    the existing record is updated in-place without committing (caller must commit).

    Args:
        barcode: Validated 10- or 14-digit item barcode.
        title: Optional human-readable item title.
        category: Item category string (default ``"book"``).

    Returns:
        The existing or newly-flushed :class:`~server.app.models.Book`.
    """
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
) -> Checkout:
    """Check out a single item to a patron.

    Args:
        card: Raw library card number (validated internally).
        barcode: Raw item barcode (validated internally).
        loan_days: Loan period in days (default 14).
        category: Item category string (default ``"book"``).
        title: Optional human-readable item title stored on first encounter.

    Returns:
        The newly-created :class:`~server.app.models.Checkout` record.

    Raises:
        ValidationError: If the card or barcode is invalid, the patron is not
            found, or the item is already checked out.
    """
    patron = Patron.query.filter_by(card_number=validate_card(card)).first()
    if not patron:
        raise ValidationError("Patron not found — register first")

    barcode = validate_barcode(barcode)

    # VBA dup check: prevent same barcode being checked out twice while active
    book = get_or_create_book(barcode, title=title, category=category)
    existing = Checkout.query.filter_by(
        book_id=book.id, action="checkout", returned_at=None
    ).first()
    if existing:
        raise ValidationError(f"Item {barcode} is already checked out")

    now = _utcnow()
    due = now + timedelta(days=loan_days)
    co = Checkout(
        patron_id=patron.id,
        book_id=book.id,
        action="checkout",
        loan_days=loan_days,
        checked_out_at=now,
        due_date=due,
    )
    db.session.add(co)
    db.session.commit()
    current_app.logger.info(
        "Checkout: patron=%s book=%s loan_days=%d", patron.masked_card, barcode, loan_days
    )
    return co


def return_item(barcode: str) -> Checkout:
    """Mark the active checkout for an item as returned and log an audit row.

    Args:
        barcode: Raw item barcode.

    Returns:
        The newly-created ``action="return"`` :class:`~server.app.models.Checkout`
        audit record.

    Raises:
        ValidationError: If the barcode is unknown or the item is not currently
            checked out.
    """
    barcode = validate_barcode(barcode)
    book = Book.query.filter_by(barcode=barcode).first()
    if not book:
        raise ValidationError(f"Unknown item {barcode}")

    active = Checkout.query.filter_by(book_id=book.id, action="checkout", returned_at=None).first()
    if not active:
        raise ValidationError(f"Item {barcode} is not currently checked out")

    active.returned_at = _utcnow()
    # Log a separate audit row for the return action
    ret = Checkout(
        patron_id=active.patron_id,
        book_id=book.id,
        action="return",
        loan_days=0,
        checked_out_at=_utcnow(),
    )
    db.session.add(ret)
    db.session.commit()
    current_app.logger.info("Return: book=%s", barcode)
    return ret


def renew_item(barcode: str, loan_days: int = 14) -> Checkout:
    """Extend the due date of an active checkout from today.

    Args:
        barcode: Raw item barcode.
        loan_days: Number of days to extend from today (default 14).

    Returns:
        The updated :class:`~server.app.models.Checkout` record.

    Raises:
        ValidationError: If the barcode is unknown or the item is not currently
            checked out.
    """
    barcode = validate_barcode(barcode)
    book = Book.query.filter_by(barcode=barcode).first()
    if not book:
        raise ValidationError(f"Unknown item {barcode}")
    active = Checkout.query.filter_by(book_id=book.id, action="checkout", returned_at=None).first()
    if not active:
        raise ValidationError(f"Item {barcode} is not currently checked out")
    active.due_date = _utcnow() + timedelta(days=loan_days)
    active.loan_days = loan_days
    db.session.commit()
    current_app.logger.info("Renew: book=%s loan_days=%d", barcode, loan_days)
    return active


def library_stats() -> dict:
    """Aggregate library-wide statistics for the dashboard.

    Returns:
        Dictionary with counts, breakdowns, and a top-books list.
    """
    now = _utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    total_patrons = Patron.query.count()
    total_books = Book.query.count()

    active_checkouts = Checkout.query.filter(
        Checkout.action == "checkout", Checkout.returned_at.is_(None)
    ).count()

    overdue_items = Checkout.query.filter(
        Checkout.action == "checkout",
        Checkout.returned_at.is_(None),
        Checkout.due_date < now,
    ).count()

    total_checkout_events = Checkout.query.filter_by(action="checkout").count()

    checkouts_today = Checkout.query.filter(
        Checkout.action == "checkout",
        Checkout.checked_out_at >= today_start,
    ).count()

    checkouts_this_week = Checkout.query.filter(
        Checkout.action == "checkout",
        Checkout.checked_out_at >= week_start,
    ).count()

    by_category = (
        db.session.query(Book.category, func.count(Checkout.id))
        .join(Checkout, Checkout.book_id == Book.id)
        .filter(Checkout.action == "checkout", Checkout.returned_at.is_(None))
        .group_by(Book.category)
        .order_by(func.count(Checkout.id).desc())
        .all()
    )

    top_books = (
        db.session.query(Book.title, Book.barcode, func.count(Checkout.id).label("cnt"))
        .join(Checkout, Checkout.book_id == Book.id)
        .filter(Checkout.action == "checkout")
        .group_by(Book.id)
        .order_by(func.count(Checkout.id).desc())
        .limit(5)
        .all()
    )

    return {
        "total_patrons": total_patrons,
        "total_books": total_books,
        "active_checkouts": active_checkouts,
        "overdue_items": overdue_items,
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


def search_patrons(query: str) -> list[Patron]:
    """Search patrons by first or last name (case-insensitive partial match).

    Args:
        query: Search string to match against first_name or last_name.

    Returns:
        List of matching :class:`~server.app.models.Patron` records, up to 50.
    """
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
    """Build the dashboard summary card.

    Args:
        card: Raw library card number (validated internally).

    Returns:
        Dictionary with patron info, counts, active items, and history.

    Raises:
        ValidationError: If the card number is invalid or patron not found.
    """
    card = validate_card(card)
    patron = Patron.query.filter_by(card_number=card).first()
    if not patron:
        raise ValidationError("Patron not found")

    all_checkouts = Checkout.query.filter_by(patron_id=patron.id, action="checkout").all()
    active = [c for c in all_checkouts if c.is_active]
    late = [c for c in active if c.is_late]
    history = (
        Checkout.query.filter_by(patron_id=patron.id).order_by(Checkout.checked_out_at.desc()).all()
    )

    return {
        "patron": patron.to_dict(),
        "account_age_days": (_utcnow() - patron.created_at).days,
        "total_checkouts": len(all_checkouts),
        "currently_out": len(active),
        "late_count": len(late),
        "active_items": [c.to_dict() for c in active],
        "history": [c.to_dict() for c in history],
    }
