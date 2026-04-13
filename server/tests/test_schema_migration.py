"""Tests for the additive-column startup schema fixer."""

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect, text

from server.app.utils.schema import ensure_schema


def _make_legacy_engine():
    """Build an in-memory SQLite database that looks like an older release."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        # Create a 'books' table missing the new columns
        conn.execute(text("""
                CREATE TABLE books (
                    id INTEGER PRIMARY KEY,
                    barcode VARCHAR(14),
                    title VARCHAR(200)
                )
                """))
        conn.execute(
            text("INSERT INTO books (id, barcode, title) VALUES (1, '9780451524935', '1984')")
        )
    return engine


def _expected_metadata():
    """Build a metadata object that includes the new columns."""
    md = MetaData()
    Table(
        "books",
        md,
        Column("id", Integer, primary_key=True),
        Column("barcode", String(14)),
        Column("title", String(200)),
        Column("author", String(120)),  # NEW
        Column("total_copies", Integer, default=1, nullable=False),  # NEW with default
        Column("is_active", Integer, default=True, nullable=False),  # NEW boolean default
    )
    return md


class TestEnsureSchema:
    def test_adds_missing_columns(self):
        engine = _make_legacy_engine()
        md = _expected_metadata()

        added = ensure_schema(engine, md)

        assert set(added) == {
            "books.author",
            "books.total_copies",
            "books.is_active",
        }

        cols = {c["name"] for c in inspect(engine).get_columns("books")}
        assert "author" in cols
        assert "total_copies" in cols
        assert "is_active" in cols

    def test_noop_when_schema_already_current(self):
        engine = _make_legacy_engine()
        md = _expected_metadata()

        # First call migrates; second call should do nothing
        ensure_schema(engine, md)
        added_again = ensure_schema(engine, md)

        assert added_again == []

    def test_existing_row_data_preserved(self):
        engine = _make_legacy_engine()
        md = _expected_metadata()

        ensure_schema(engine, md)

        with engine.begin() as conn:
            row = conn.execute(text("SELECT barcode, title FROM books WHERE id = 1")).fetchone()
        assert row is not None
        assert row[0] == "9780451524935"
        assert row[1] == "1984"

    def test_literal_default_is_backfilled(self):
        engine = _make_legacy_engine()
        md = _expected_metadata()

        ensure_schema(engine, md)

        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT total_copies, is_active FROM books WHERE id = 1")
            ).fetchone()
        assert row is not None
        assert row[0] == 1  # total_copies default
        assert row[1] == 1  # is_active default (True → 1)

    def test_ignores_unknown_tables(self):
        engine = _make_legacy_engine()
        md = MetaData()
        Table(
            "nonexistent",
            md,
            Column("id", Integer, primary_key=True),
            Column("foo", String(50)),
        )

        added = ensure_schema(engine, md)

        # Tables that don't exist yet are create_all()'s job, not ours
        assert added == []

    def test_runs_against_live_app_db(self, app):
        """Sanity check: ensure_schema on a freshly-created app DB finds nothing to add."""
        from server.app.database import db
        from server.app.utils.schema import ensure_schema

        added = ensure_schema(db.engine, db.metadata)
        assert added == []
