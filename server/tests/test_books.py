"""Tests for book catalog endpoints and the next-card patron endpoint."""

import json
from unittest.mock import MagicMock, patch


# ── POST /api/books/ ─────────────────────────────────────────────────────────


class TestAddBook:
    def test_add_book_isbn13(self, client):
        r = client.post(
            "/api/books/",
            json={
                "barcode": "9780451524935",
                "title": "Nineteen Eighty-Four",
                "author": "George Orwell",
                "category": "book",
            },
        )
        assert r.status_code == 201
        data = r.get_json()
        assert data["barcode"] == "9780451524935"
        assert data["title"] == "Nineteen Eighty-Four"
        assert data["author"] == "George Orwell"
        assert data["category"] == "book"

    def test_add_book_isbn10(self, client):
        r = client.post("/api/books/", json={"barcode": "0451524934"})
        assert r.status_code == 201
        assert r.get_json()["barcode"] == "0451524934"

    def test_add_book_14_digit_barcode(self, client):
        r = client.post("/api/books/", json={"barcode": "12345678901234"})
        assert r.status_code == 201

    def test_add_book_minimal_fields(self, client):
        """Barcode is the only required field; title/author/category are optional."""
        r = client.post("/api/books/", json={"barcode": "9780451524935"})
        assert r.status_code == 201
        data = r.get_json()
        assert data["title"] is None
        assert data["author"] is None
        assert data["category"] == "book"

    def test_add_book_explicit_category(self, client):
        r = client.post(
            "/api/books/",
            json={
                "barcode": "9780451524935",
                "category": "dvd",
            },
        )
        assert r.status_code == 201
        assert r.get_json()["category"] == "dvd"

    def test_add_book_duplicate_barcode_returns_400(self, client):
        client.post("/api/books/", json={"barcode": "9780451524935", "title": "First"})
        r = client.post("/api/books/", json={"barcode": "9780451524935", "title": "Dupe"})
        assert r.status_code == 400
        assert "already in the catalog" in r.get_json()["error"]

    def test_add_book_invalid_barcode_non_numeric(self, client):
        r = client.post("/api/books/", json={"barcode": "ISBN-978-0451524935"})
        assert r.status_code == 400

    def test_add_book_invalid_barcode_wrong_length(self, client):
        r = client.post("/api/books/", json={"barcode": "12345"})
        assert r.status_code == 400

    def test_add_book_missing_barcode(self, client):
        r = client.post("/api/books/", json={"title": "No barcode"})
        assert r.status_code == 400

    def test_added_book_is_checkable(self, client, patron):
        """A book added via /api/books/ can subsequently be checked out."""
        client.post("/api/books/", json={"barcode": "9780451524935", "title": "1984"})
        r = client.post(
            "/api/checkouts/",
            json={
                "card_number": "1234567890",
                "barcode": "9780451524935",
            },
        )
        assert r.status_code == 201


# ── GET /api/books/lookup ─────────────────────────────────────────────────────


class TestLookupIsbn:
    def _make_google_mock(self, title="Test Title", authors=None, categories=None):
        """Return a context-manager mock that simulates a Google Books response."""
        payload = {
            "items": [
                {
                    "volumeInfo": {
                        "title": title,
                        "authors": authors or ["Test Author"],
                        "categories": categories or ["Fiction"],
                        "publishedDate": "2001",
                        "description": "A test book description.",
                    }
                }
            ]
        }
        mock = MagicMock()
        mock.__enter__ = lambda s: s
        mock.__exit__ = MagicMock(return_value=False)
        mock.read.return_value = json.dumps(payload).encode()
        return mock

    def test_lookup_found(self, client):
        with patch(
            "server.app.routes.books.urllib.request.urlopen", return_value=self._make_google_mock()
        ):
            r = client.get("/api/books/lookup?isbn=9780451524935")
        assert r.status_code == 200
        data = r.get_json()
        assert data["found"] is True
        assert data["title"] == "Test Title"
        assert data["author"] == "Test Author"
        assert data["category"] == "book"

    def test_lookup_dvd_category_mapping(self, client):
        with patch(
            "server.app.routes.books.urllib.request.urlopen",
            return_value=self._make_google_mock(categories=["DVD & Film"]),
        ):
            r = client.get("/api/books/lookup?isbn=9780451524935")
        assert r.get_json()["category"] == "dvd"

    def test_lookup_audiobook_category_mapping(self, client):
        with patch(
            "server.app.routes.books.urllib.request.urlopen",
            return_value=self._make_google_mock(categories=["Audiobook"]),
        ):
            r = client.get("/api/books/lookup?isbn=9780451524935")
        assert r.get_json()["category"] == "audiobook"

    def test_lookup_not_found(self, client):
        payload = {"totalItems": 0, "items": []}
        mock = MagicMock()
        mock.__enter__ = lambda s: s
        mock.__exit__ = MagicMock(return_value=False)
        mock.read.return_value = json.dumps(payload).encode()
        with patch("server.app.routes.books.urllib.request.urlopen", return_value=mock):
            r = client.get("/api/books/lookup?isbn=9999999999999")
        assert r.status_code == 200
        assert r.get_json()["found"] is False

    def test_lookup_service_unavailable(self, client):
        import urllib.error

        with patch(
            "server.app.routes.books.urllib.request.urlopen",
            side_effect=urllib.error.URLError("timeout"),
        ):
            r = client.get("/api/books/lookup?isbn=9780451524935")
        assert r.status_code == 200
        data = r.get_json()
        assert data["found"] is False

    def test_lookup_missing_isbn_param(self, client):
        r = client.get("/api/books/lookup")
        assert r.status_code == 400

    def test_lookup_non_numeric_isbn(self, client):
        r = client.get("/api/books/lookup?isbn=not-a-number")
        assert r.status_code == 400


# ── GET /api/patrons/next-card ────────────────────────────────────────────────


class TestNextCard:
    def test_returns_14_digit_number_on_empty_db(self, client):
        r = client.get("/api/patrons/next-card")
        assert r.status_code == 200
        data = r.get_json()
        assert "card_number" in data
        assert data["card_number"] == "10000000000001"
        assert len(data["card_number"]) == 14

    def test_increments_from_highest_existing_card(self, client):
        # Register a patron with a specific 14-digit card
        client.post(
            "/api/patrons/",
            json={
                "card_number": "10000000000005",
                "first_name": "Alice",
                "last_name": "Smith",
                "birth_date": "1990-01-01",
            },
        )
        r = client.get("/api/patrons/next-card")
        assert r.get_json()["card_number"] == "10000000000006"

    def test_ignores_short_cards_below_14digit_base(self, client):
        # A 10-digit card is numerically smaller than the 14-digit base,
        # so next-card should still start at the base.
        client.post(
            "/api/patrons/",
            json={
                "card_number": "9999999999",
                "first_name": "Bob",
                "last_name": "Jones",
                "birth_date": "1985-06-15",
            },
        )
        r = client.get("/api/patrons/next-card")
        assert r.get_json()["card_number"] == "10000000000001"

    def test_sequential_calls_return_same_number_without_registration(self, client):
        """next-card is read-only — it doesn't consume a number."""
        r1 = client.get("/api/patrons/next-card")
        r2 = client.get("/api/patrons/next-card")
        assert r1.get_json()["card_number"] == r2.get_json()["card_number"]
