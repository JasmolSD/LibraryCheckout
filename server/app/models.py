"""SQLAlchemy models — Patron, Book, Checkout."""

from __future__ import annotations

from datetime import datetime
from .database import db


class Patron(db.Model):
    __tablename__ = "patrons"

    id = db.Column(db.Integer, primary_key=True)
    card_number = db.Column(db.String(14), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    checkouts = db.relationship(
        "Checkout", backref="patron", lazy="dynamic", cascade="all, delete-orphan"
    )

    @property
    def masked_card(self) -> str:
        return "**" + self.card_number[-4:]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "card_number": self.card_number,
            "card_masked": self.masked_card,
            "name": self.name,
            "email": self.email,
            "created_at": self.created_at.isoformat(),
        }


class Book(db.Model):
    __tablename__ = "books"

    id = db.Column(db.Integer, primary_key=True)
    barcode = db.Column(db.String(14), unique=True, nullable=False, index=True)
    title = db.Column(db.String(200), nullable=True)
    author = db.Column(db.String(120), nullable=True)
    category = db.Column(db.String(40), default="book", nullable=False)
    # categories: book, dvd, audiobook, magazine, ebook, other
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    checkouts = db.relationship("Checkout", backref="book", lazy="dynamic")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "barcode": self.barcode,
            "title": self.title,
            "author": self.author,
            "category": self.category,
        }


class Checkout(db.Model):
    __tablename__ = "checkouts"

    id = db.Column(db.Integer, primary_key=True)
    patron_id = db.Column(db.Integer, db.ForeignKey("patrons.id"), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey("books.id"), nullable=False)

    # action: checkout | return | renew
    action = db.Column(db.String(20), default="checkout", nullable=False)
    weeks = db.Column(db.Integer, default=3, nullable=False)

    checked_out_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    due_date = db.Column(db.DateTime, nullable=True)
    returned_at = db.Column(db.DateTime, nullable=True)

    @property
    def is_active(self) -> bool:
        return self.action == "checkout" and self.returned_at is None

    @property
    def is_late(self) -> bool:
        return self.is_active and self.due_date is not None and self.due_date < datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "patron_id": self.patron_id,
            "book_id": self.book_id,
            "barcode": self.book.barcode if self.book else None,
            "title": self.book.title if self.book else None,
            "category": self.book.category if self.book else None,
            "action": self.action,
            "weeks": self.weeks,
            "checked_out_at": self.checked_out_at.isoformat(),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "returned_at": self.returned_at.isoformat() if self.returned_at else None,
            "is_active": self.is_active,
            "is_late": self.is_late,
        }
