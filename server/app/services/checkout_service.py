"""Checkout business logic — port of VBA Barcode() / addmaterials() subs."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from flask import current_app

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

    all_checkouts = patron.checkouts.filter_by(action="checkout").all()
    active = [c for c in all_checkouts if c.is_active]
    late = [c for c in active if c.is_late]

    return {
        "patron": patron.to_dict(),
        "account_age_days": (_utcnow() - patron.created_at).days,
        "total_checkouts": len(all_checkouts),
        "currently_out": len(active),
        "late_count": len(late),
        "active_items": [c.to_dict() for c in active],
        "history": [
            c.to_dict() for c in patron.checkouts.order_by(Checkout.checked_out_at.desc()).all()
        ],
    }
