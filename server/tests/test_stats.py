"""Tests for GET /api/stats and GET /api/checkouts/overdue."""

from datetime import UTC, datetime, timedelta

from server.app.database import db
from server.app.models import Loan

# ── GET /api/stats ────────────────────────────────────────────────────────────


class TestStats:
    def test_stats_empty_db(self, client):
        r = client.get("/api/stats")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total_patrons"] == 0
        assert data["total_books"] == 0
        assert data["active_titles"] == 0
        assert data["total_copies"] == 0
        assert data["active_checkouts"] == 0
        assert data["overdue_items"] == 0
        assert data["total_checkout_events"] == 0
        assert data["checkouts_today"] == 0
        assert data["checkouts_this_week"] == 0
        assert data["by_category"] == []
        assert data["top_books"] == []
        assert "generated_at" in data

    def test_stats_counts_patron(self, client, patron):
        r = client.get("/api/stats")
        assert r.get_json()["total_patrons"] == 1

    def test_stats_counts_book_added_to_catalog(self, client):
        client.post("/api/books/", json={"barcode": "9780451524935", "title": "1984"})
        r = client.get("/api/stats")
        data = r.get_json()
        assert data["total_books"] == 1
        assert data["total_copies"] == 1

    def test_stats_total_books_counts_ids_not_copies(self, client):
        """total_books is a count of unique Book rows, not a sum of quantities."""
        client.post(
            "/api/books/",
            json={"barcode": "9780451524935", "title": "1984", "quantity": 5},
        )
        client.post(
            "/api/books/",
            json={"barcode": "0451524934", "title": "Animal Farm", "quantity": 3},
        )
        data = client.get("/api/stats").get_json()
        assert data["total_books"] == 2  # two unique IDs
        assert data["total_copies"] == 8  # 5 + 3 physical copies

    def test_stats_active_titles_excludes_archived(self, client):
        """active_titles counts non-archived book rows; total_books counts everything."""
        client.post("/api/books/", json={"barcode": "9780451524935", "title": "1984"})
        client.post("/api/books/", json={"barcode": "0451524934", "title": "Animal Farm"})
        client.post("/api/books/9780451524935/archive")

        data = client.get("/api/stats?refresh=1").get_json()
        assert data["total_books"] == 2  # both rows still exist
        assert data["active_titles"] == 1  # one archived

    def test_stats_total_copies_tracks_inventory_updates(self, client):
        client.post(
            "/api/books/",
            json={"barcode": "9780451524935", "quantity": 2},
        )
        assert client.get("/api/stats?refresh=1").get_json()["total_copies"] == 2
        client.post("/api/books/9780451524935/quantity", json={"total_copies": 7})
        assert client.get("/api/stats?refresh=1").get_json()["total_copies"] == 7

    def test_stats_active_checkout_increments_count(self, client, patron):
        client.post(
            "/api/checkouts/",
            json={
                "card_number": "1234567890",
                "barcode": "9780451524935",
                "title": "1984",
            },
        )
        r = client.get("/api/stats")
        data = r.get_json()
        assert data["active_checkouts"] == 1
        assert data["total_checkout_events"] == 1
        assert data["checkouts_today"] == 1
        assert data["checkouts_this_week"] == 1
        assert data["total_books"] == 1

    def test_stats_return_decrements_active(self, client, patron):
        client.post(
            "/api/checkouts/",
            json={
                "card_number": "1234567890",
                "barcode": "9780451524935",
            },
        )
        client.post("/api/checkouts/return", json={"barcode": "9780451524935"})
        data = client.get("/api/stats").get_json()
        assert data["active_checkouts"] == 0
        assert data["total_checkout_events"] == 1  # return doesn't add a checkout event

    def test_stats_by_category_groups_active_checkouts(self, client, patron):
        client.post(
            "/api/checkouts/",
            json={
                "card_number": "1234567890",
                "barcode": "9780451524935",
                "category": "dvd",
            },
        )
        data = client.get("/api/stats").get_json()
        cats = {row["category"]: row["count"] for row in data["by_category"]}
        assert cats.get("dvd") == 1

    def test_stats_top_books_lists_most_borrowed(self, client, patron):
        # Checkout and return the same book twice to make it the top item
        client.post(
            "/api/checkouts/",
            json={
                "card_number": "1234567890",
                "barcode": "9780451524935",
                "title": "1984",
            },
        )
        client.post("/api/checkouts/return", json={"barcode": "9780451524935"})
        client.post(
            "/api/checkouts/",
            json={
                "card_number": "1234567890",
                "barcode": "9780451524935",
            },
        )
        data = client.get("/api/stats").get_json()
        assert len(data["top_books"]) == 1
        assert data["top_books"][0]["title"] == "1984"
        assert data["top_books"][0]["checkouts"] == 2

    def test_stats_overdue_count_reflects_past_due(self, client, patron):
        client.post(
            "/api/checkouts/",
            json={
                "card_number": "1234567890",
                "barcode": "9780451524935",
            },
        )
        # Force the due_date into the past
        loan = Loan.query.filter(Loan.returned_at.is_(None)).first()
        assert loan is not None
        loan.due_date = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=3)
        db.session.commit()

        data = client.get("/api/stats").get_json()
        assert data["overdue_items"] == 1
        assert data["active_checkouts"] == 1  # still active, just late


# ── GET /api/checkouts/overdue ────────────────────────────────────────────────


class TestOverdue:
    def test_overdue_empty_db(self, client):
        r = client.get("/api/checkouts/overdue")
        assert r.status_code == 200
        data = r.get_json()
        assert data["count"] == 0
        assert data["overdue"] == []

    def test_overdue_no_late_items(self, client, patron):
        client.post(
            "/api/checkouts/",
            json={
                "card_number": "1234567890",
                "barcode": "9780451524935",
            },
        )
        data = client.get("/api/checkouts/overdue").get_json()
        assert data["count"] == 0

    def test_overdue_returns_late_item_details(self, client, patron):
        client.post(
            "/api/checkouts/",
            json={
                "card_number": "1234567890",
                "barcode": "9780451524935",
                "title": "Nineteen Eighty-Four",
            },
        )
        loan = Loan.query.filter(Loan.returned_at.is_(None)).first()
        assert loan is not None
        loan.due_date = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
        db.session.commit()

        data = client.get("/api/checkouts/overdue").get_json()
        assert data["count"] == 1
        row = data["overdue"][0]
        assert row["patron_name"] == "DOE, JANE"
        assert row["card_number"] == "1234567890"
        assert row["barcode"] == "9780451524935"
        assert row["item_title"] == "Nineteen Eighty-Four"
        assert row["days_overdue"] >= 7

    def test_overdue_excludes_returned_items(self, client, patron):
        client.post(
            "/api/checkouts/",
            json={
                "card_number": "1234567890",
                "barcode": "9780451524935",
            },
        )
        loan = Loan.query.filter(Loan.returned_at.is_(None)).first()
        assert loan is not None
        loan.due_date = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=5)
        db.session.commit()

        client.post("/api/checkouts/return", json={"barcode": "9780451524935"})
        data = client.get("/api/checkouts/overdue").get_json()
        assert data["count"] == 0

    def test_overdue_sorted_most_overdue_first(self, client, patron):
        # Check out two books and make them overdue by different amounts
        client.post(
            "/api/checkouts/",
            json={
                "card_number": "1234567890",
                "barcode": "9780451524935",
                "title": "Book A",
            },
        )
        client.post(
            "/api/checkouts/",
            json={
                "card_number": "1234567890",
                "barcode": "0451524934",
                "title": "Book B",
            },
        )
        rows = Loan.query.filter(Loan.returned_at.is_(None)).all()
        rows[0].due_date = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=10)
        rows[1].due_date = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)
        db.session.commit()

        data = client.get("/api/checkouts/overdue").get_json()
        assert data["count"] == 2
        # Most overdue should be first (ascending due_date order)
        assert data["overdue"][0]["days_overdue"] >= data["overdue"][1]["days_overdue"]

    def test_overdue_response_includes_required_fields(self, client, patron):
        client.post(
            "/api/checkouts/",
            json={
                "card_number": "1234567890",
                "barcode": "9780451524935",
                "title": "1984",
                "category": "book",
            },
        )
        loan = Loan.query.filter(Loan.returned_at.is_(None)).first()
        assert loan is not None
        loan.due_date = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        db.session.commit()

        row = client.get("/api/checkouts/overdue").get_json()["overdue"][0]
        required = {
            "patron_name",
            "card_number",
            "card_masked",
            "item_title",
            "barcode",
            "category",
            "checked_out_at",
            "due_date",
            "days_overdue",
        }
        assert required.issubset(row.keys())
