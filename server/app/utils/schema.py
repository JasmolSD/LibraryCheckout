"""Lightweight startup schema migration — additive columns only.

When the model schema grows new columns between releases, SQLAlchemy's
``create_all()`` does *not* alter existing tables, so an end-user who
upgrades their ``.exe`` would otherwise hit ``no such column`` errors
against their old ``library.db``.

This module inspects every table known to SQLAlchemy's metadata, checks
the live SQLite schema, and runs ``ALTER TABLE ... ADD COLUMN`` for any
columns that are missing.  It only handles **additive** changes — it
never drops, renames, or retypes existing columns.  Destructive changes
still require a one-off migration script.

Usage::

    from .utils.schema import ensure_schema
    added = ensure_schema(db.engine, db.metadata)
    if added:
        app.logger.info("Added missing columns: %s", ", ".join(added))
"""

from __future__ import annotations

from sqlalchemy import Column, MetaData, inspect, text
from sqlalchemy.dialects import sqlite
from sqlalchemy.engine import Engine


def ensure_schema(engine: Engine, metadata: MetaData) -> list[str]:
    """Add any missing columns to existing tables in ``engine``'s database.

    Args:
        engine: SQLAlchemy engine bound to the live database.
        metadata: The metadata object whose tables describe the *expected*
            schema (typically ``db.metadata``).

    Returns:
        A list of ``"table.column"`` strings describing every column that
        was added — empty if the schema was already up to date.
    """
    added: list[str] = []
    inspector = inspect(engine)

    for table_name, table in metadata.tables.items():
        if not inspector.has_table(table_name):
            # New tables are handled by create_all(); nothing to do here.
            continue
        existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name in existing_cols:
                continue
            col_sql = _render_add_column(column)
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_sql}"))
            added.append(f"{table_name}.{column.name}")

    return added


def _render_add_column(column: Column) -> str:
    """Render a SQLite ``ALTER TABLE ... ADD COLUMN`` fragment for ``column``.

    Handles the common case of new nullable / defaulted columns. If the
    column is NOT NULL without a literal default, falls back to nullable
    so the migration doesn't fail against an existing non-empty table —
    SQLite won't let you add a ``NOT NULL`` column without a default.
    """
    name = column.name
    col_type = column.type.compile(dialect=sqlite.dialect())
    parts: list[str] = [name, col_type]

    default_sql = _literal_default(column)
    if default_sql is not None:
        parts.append(f"DEFAULT {default_sql}")

    # Only enforce NOT NULL when we have a usable default to back-fill with.
    if not column.nullable and default_sql is not None:
        parts.append("NOT NULL")

    return " ".join(parts)


def _literal_default(column: Column) -> str | None:
    """Return a SQLite literal for ``column``'s default, or None.

    Callable defaults (e.g. ``_utcnow``) and SQL-expression defaults are
    skipped — they can't be inlined into an ``ALTER TABLE`` statement,
    so the added column will simply start out NULL and get populated on
    the next write.
    """
    if column.default is None:
        return None

    # SQLAlchemy wraps scalars in ColumnDefault with a .arg attribute.
    arg = getattr(column.default, "arg", None)
    if arg is None or callable(arg):
        return None

    if isinstance(arg, bool):
        return "1" if arg else "0"
    if isinstance(arg, (int, float)):
        return str(arg)
    if isinstance(arg, str):
        escaped = arg.replace("'", "''")
        return f"'{escaped}'"

    return None
