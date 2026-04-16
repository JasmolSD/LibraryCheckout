"""One-shot data migration: SQLite -> PostgreSQL (e.g. Supabase).

Run this once when you're cutting over from the desktop SQLite database
to a hosted Postgres backend.  It reads every row of every model from
the source SQLite file and inserts it into the destination Postgres
database, preserving primary keys so foreign-key references stay intact.

After the bulk insert, it advances each Postgres sequence past the
highest imported ID, so subsequent inserts don't collide with the data
you just migrated.

Usage (from the repo root)::

    # 1. Make sure the source SQLite DB has everything you want to keep.
    # 2. Set DATABASE_URL in .env to your Postgres connection string
    #    (e.g. from Supabase → Project Settings → Database → URI).
    # 3. Install psycopg: uv sync --group postgres
    # 4. Run:
    uv run python scripts/migrate_sqlite_to_postgres.py

By default the script reads from ``data/library.db`` relative to the
repo root. Override with ``--sqlite PATH`` if yours lives elsewhere.

The destination database must already exist and be reachable. Tables
will be created automatically on first connect by
``db.create_all()``.  If any of the destination tables already contain
rows, the script aborts so you don't accidentally clobber live data.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, func, insert, select, text
from sqlalchemy.orm import Session


def _log(msg: str) -> None:
    print(f"[migrate] {msg}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "library.db",
        help="Path to the source SQLite database (default: data/library.db).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    args = parser.parse_args()

    if not args.sqlite.exists():
        _log(f"Source SQLite file not found: {args.sqlite}")
        return 1

    dest_url = os.environ.get("DATABASE_URL", "").strip()
    if not dest_url:
        _log("DATABASE_URL is not set. Put the Postgres URI in your .env first.")
        return 1
    if not dest_url.startswith(("postgresql://", "postgresql+")):
        _log(f"DATABASE_URL does not look like a Postgres URL: {dest_url}")
        return 1

    # Ensure the SQLAlchemy URL uses the psycopg (v3) driver.
    if dest_url.startswith("postgresql://"):
        dest_url = dest_url.replace("postgresql://", "postgresql+psycopg://", 1)

    _log(f"Source: {args.sqlite}")
    _log(f"Target: {dest_url.split('@')[-1]}  (credentials hidden)")

    if not args.yes:
        answer = input("\nProceed with migration? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            _log("Aborted.")
            return 0

    # Import the models by bootstrapping a Flask app context so all
    # relationships and metadata are wired up the same way the live
    # app does them.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from server.app import create_app  # noqa: E402
    from server.app.database import db  # noqa: E402
    from server.app.models import Book, Loan, Patron, Transaction  # noqa: E402

    app = create_app("production")

    src_engine = create_engine(f"sqlite:///{args.sqlite}")
    dst_engine = create_engine(dest_url)

    # Create destination schema if missing.
    with app.app_context():
        db.metadata.create_all(dst_engine)

    # Pre-flight: refuse to run if the destination already has data.
    with Session(dst_engine) as dst:
        for model in (Patron, Book, Loan, Transaction):
            count = dst.scalar(select(func.count()).select_from(model))
            if count and count > 0:
                _log(
                    f"Destination already has {count} rows in "
                    f"{model.__tablename__!r}. Refusing to proceed."
                )
                return 1

    # Bulk-copy in FK-safe order: Patron, Book, Loan, Transaction.
    # Loan depends on Patron + Book, Transaction depends on Loan.
    model_order = (Patron, Book, Loan, Transaction)
    totals: dict[str, int] = {}

    with Session(src_engine) as src, Session(dst_engine) as dst:
        for model in model_order:
            rows = src.scalars(select(model)).all()
            _log(f"{model.__tablename__}: {len(rows)} row(s)")
            from sqlalchemy import Table  # local import keeps pyright happy

            table: Table = model.__table__  # type: ignore[assignment]
            for row in rows:
                # Detach from source and rebuild as a plain dict of columns
                # so we can insert the same PK into the destination.
                payload = {c.name: getattr(row, c.name) for c in table.columns}
                dst.execute(insert(table).values(**payload))
            totals[model.__tablename__] = len(rows)
        dst.commit()

    # Bump each Postgres sequence so the next INSERT doesn't collide
    # with the IDs we just brought over.
    with dst_engine.begin() as conn:
        for model in model_order:
            table = model.__tablename__
            conn.execute(
                text(
                    f"SELECT setval("
                    f"  pg_get_serial_sequence('{table}', 'id'),"
                    f"  COALESCE((SELECT MAX(id) FROM {table}), 1),"
                    f"  (SELECT MAX(id) IS NOT NULL FROM {table})"
                    f")"
                )
            )

    _log("")
    _log("Migration complete!")
    for name, count in totals.items():
        _log(f"  {name}: {count} row(s)")
    _log("")
    _log("You can now launch the app with DATABASE_URL still set —")
    _log("it will run against the new Postgres database.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
