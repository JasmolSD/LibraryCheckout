"""Checkout business logic — port of VBA Barcode() / addmaterials() subs."""

from __future__ import annotations

from datetime import datetime, timedelta
from flask import current_app

from ..database import db
from ..models import Book, Checkout, Patron
from .validators import (
    ValidationError,
    normalize_name,
    parse_checkout_prefix,
    validate_card,
)


def get_or_create_patron(card: str, name: str | None = None, email: str | None = None) -> Patron:
    card = validate_card(card)
    patron = Patron.query.filter_by(card_number=card).first()
    if patron:
        return patron
    if not name:
        raise ValidationError("Name required for new patron registration")
    patron = Patron(card_number=card, name=normalize_name(name), email=email)
    db.session.add(patron)
    db.session.commit()
    current_app.logger.info("Registered new patron %s", patron.masked_card)
    return patron


def get_or_create_book(barcode: str, title: str | None = None, category: str = "book") -> Book:
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
    card: str, item_input: str, category: str = "book", title: str | None = None
) -> Checkout:
    """Check out a single item to a patron.

    Mirrors the VBA flow: validate card, parse 3W/2W prefix, dedupe active
    checkouts of the same barcode, compute due date.
    """
    patron = Patron.query.filter_by(card_number=validate_card(card)).first()
    if not patron:
        raise ValidationError("Patron not found — register first")

    barcode, weeks = parse_checkout_prefix(item_input)

    # VBA dup check: prevent same barcode being checked out twice while active
    book = get_or_create_book(barcode, title=title, category=category)
    existing = Checkout.query.filter_by(
        book_id=book.id, action="checkout", returned_at=None
    ).first()
    if existing:
        raise ValidationError(f"Item {barcode} is already checked out")

    now = datetime.utcnow()
    due = now + timedelta(weeks=weeks)
    co = Checkout(
        patron_id=patron.id,
        book_id=book.id,
        action="checkout",
        weeks=weeks,
        checked_out_at=now,
        due_date=due,
    )
    db.session.add(co)
    db.session.commit()
    current_app.logger.info(
        "Checkout: patron=%s book=%s weeks=%d", patron.masked_card, barcode, weeks
    )
    return co


def return_item(barcode: str) -> Checkout:
    barcode = parse_checkout_prefix(barcode)[0]
    book = Book.query.filter_by(barcode=barcode).first()
    if not book:
        raise ValidationError(f"Unknown item {barcode}")

    active = Checkout.query.filter_by(book_id=book.id, action="checkout", returned_at=None).first()
    if not active:
        raise ValidationError(f"Item {barcode} is not currently checked out")

    active.returned_at = datetime.utcnow()
    # Log a separate audit row for the return action
    ret = Checkout(
        patron_id=active.patron_id,
        book_id=book.id,
        action="return",
        weeks=0,
        checked_out_at=datetime.utcnow(),
    )
    db.session.add(ret)
    db.session.commit()
    current_app.logger.info("Return: book=%s", barcode)
    return ret


def renew_item(barcode: str, weeks: int = 3) -> Checkout:
    barcode = parse_checkout_prefix(barcode)[0]
    book = Book.query.filter_by(barcode=barcode).first()
    if not book:
        raise ValidationError(f"Unknown item {barcode}")
    active = Checkout.query.filter_by(book_id=book.id, action="checkout", returned_at=None).first()
    if not active:
        raise ValidationError(f"Item {barcode} is not currently checked out")
    active.due_date = datetime.utcnow() + timedelta(weeks=weeks)
    active.weeks = weeks
    db.session.commit()
    current_app.logger.info("Renew: book=%s weeks=%d", barcode, weeks)
    return active


def patron_summary(card: str) -> dict:
    """Build the dashboard summary card."""
    card = validate_card(card)
    patron = Patron.query.filter_by(card_number=card).first()
    if not patron:
        raise ValidationError("Patron not found")

    all_checkouts = patron.checkouts.filter_by(action="checkout").all()
    active = [c for c in all_checkouts if c.is_active]
    late = [c for c in active if c.is_late]

    return {
        "patron": patron.to_dict(),
        "account_age_days": (datetime.utcnow() - patron.created_at).days,
        "total_checkouts": len(all_checkouts),
        "currently_out": len(active),
        "late_count": len(late),
        "active_items": [c.to_dict() for c in active],
        "history": [
            c.to_dict() for c in patron.checkouts.order_by(Checkout.checked_out_at.desc()).all()
        ],
    }
