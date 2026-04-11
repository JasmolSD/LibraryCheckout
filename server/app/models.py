"""SQLAlchemy models — Patron, Book, Loan, Transaction."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base, db

# At type-check time extend the typed DeclarativeBase so pyright can infer
# constructor signatures from Mapped[T] fields.  At runtime extend db.Model
# so Flask-SQLAlchemy's session, query proxy, and table registration all work.
if TYPE_CHECKING:
    _Base = Base
else:
    _Base = db.Model


def _utcnow() -> datetime:
    """Return current UTC time as a naive datetime (SQLite-compatible)."""
    return datetime.now(UTC).replace(tzinfo=None)


class Patron(_Base):
    __tablename__ = "patrons"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_number: Mapped[str] = mapped_column(String(14), unique=True, index=True)
    last_name: Mapped[str] = mapped_column(String(60))
    first_name: Mapped[str] = mapped_column(String(60))
    middle_name: Mapped[str | None] = mapped_column(String(60))
    birth_date: Mapped[date] = mapped_column()
    email: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    loans: Mapped[list[Loan]] = relationship(
        back_populates="patron", cascade="all, delete-orphan"
    )

    @property
    def name(self) -> str:
        """Full name in LAST, FIRST display format."""
        return f"{self.last_name}, {self.first_name}"

    @property
    def masked_card(self) -> str:
        return "**" + self.card_number[-4:]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "card_number": self.card_number,
            "card_masked": self.masked_card,
            "last_name": self.last_name,
            "first_name": self.first_name,
            "middle_name": self.middle_name,
            "name": self.name,
            "birth_date": self.birth_date.isoformat() if self.birth_date else None,
            "email": self.email,
            "phone": self.phone,
            "created_at": self.created_at.isoformat(),
        }


class Book(_Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    barcode: Mapped[str] = mapped_column(String(14), unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(200))
    author: Mapped[str | None] = mapped_column(String(120))
    # categories: book, dvd, audiobook, magazine, ebook, other
    category: Mapped[str] = mapped_column(String(40), default="book")
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    loans: Mapped[list[Loan]] = relationship(back_populates="book")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "barcode": self.barcode,
            "title": self.title,
            "author": self.author,
            "category": self.category,
        }


class Loan(_Base):
    """Tracks the state of a single book borrowing."""

    __tablename__ = "loans"

    id: Mapped[int] = mapped_column(primary_key=True)
    patron_id: Mapped[int] = mapped_column(ForeignKey("patrons.id"), index=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    loan_days: Mapped[int] = mapped_column(default=14)
    checked_out_at: Mapped[datetime] = mapped_column(default=_utcnow)
    due_date: Mapped[datetime | None] = mapped_column()
    returned_at: Mapped[datetime | None] = mapped_column()

    patron: Mapped[Patron] = relationship(back_populates="loans")
    book: Mapped[Book] = relationship(back_populates="loans")
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="loan", cascade="all, delete-orphan"
    )

    @property
    def is_active(self) -> bool:
        return self.returned_at is None

    @property
    def is_late(self) -> bool:
        return self.is_active and self.due_date is not None and self.due_date < _utcnow()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "patron_id": self.patron_id,
            "book_id": self.book_id,
            "barcode": self.book.barcode if self.book else None,
            "title": self.book.title if self.book else None,
            "category": self.book.category if self.book else None,
            "loan_days": self.loan_days,
            "checked_out_at": self.checked_out_at.isoformat(),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "returned_at": self.returned_at.isoformat() if self.returned_at else None,
            "is_active": self.is_active,
            "is_late": self.is_late,
        }


class Transaction(_Base):
    """Immutable audit trail — one row per checkout, return, or renew event."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"), index=True)
    # action: checkout | return | renew
    action: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    loan: Mapped[Loan] = relationship(back_populates="transactions")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "loan_id": self.loan_id,
            "action": self.action,
            "created_at": self.created_at.isoformat(),
            "barcode": self.loan.book.barcode if self.loan and self.loan.book else None,
            "title": self.loan.book.title if self.loan and self.loan.book else None,
            "category": self.loan.book.category if self.loan and self.loan.book else None,
            "checked_out_at": self.loan.checked_out_at.isoformat() if self.loan else None,
            "due_date": self.loan.due_date.isoformat() if self.loan and self.loan.due_date else None,
            "returned_at": self.loan.returned_at.isoformat() if self.loan and self.loan.returned_at else None,
            "is_late": self.loan.is_late if self.loan else False,
        }
