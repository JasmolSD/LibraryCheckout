"""SQLAlchemy database instance — imported by models and the app factory."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    # Let pyright know that all model subclasses have a .query attribute at
    # type-check time.  At runtime Flask-SQLAlchemy injects this via its own
    # Model mixin; we only need the annotation here.
    if TYPE_CHECKING:
        query: ClassVar[Any]


db = SQLAlchemy(model_class=Base)
