"""Tests for book catalog endpoints, book details, and the next-card patron endpoint."""

import json
from unittest.mock import MagicMock, patch

# ── GET /api/books/search ────────────────────────────────────────────────────


class TestSearchBooks:
    def _seed(self, client):
        client.post(
            "/api/books/",
            json={
                "barcode": "9780451524935",
                "title": "Nineteen Eighty-Four",
                "author": "George Orwell",
            },
        )
        client.post(
            "/api/books/",
            json={
                "barcode": "9780451524936",
                "title": "Animal Farm",
                "author": "George Orwell",
            },
        )
        client.post(
            "/api/books/",
            json={
                "barcode": "4560000340000",
                "title": "The Great Gatsby",
                "author": "F. Scott Fitzgerald",
            },
        )
        client.post(
            "/api/books/",
            json={
                "barcode": "4560000340001",
                "title": "Tender Is the Night",
                "author": "F. Scott Fitzgerald",
            },
        )

    def test_search_missing_q_returns_400(self, client):
        r = client.get("/api/books/search")
        assert r.status_code == 400

    def test_search_by_barcode_prefix(self, client):
        self._seed(client)
        r = client.get("/api/books/search?q=978045152")
        assert r.status_code == 200
        results = r.get_json()
        barcodes = {b["barcode"] for b in results}
        assert "9780451524935" in barcodes
        assert "9780451524936" in barcodes

    def test_search_by_title_contains(self, client):
        self._seed(client)
        r = client.get("/api/books/search?q=Gatsby")
        results = r.get_json()
        assert any(b["barcode"] == "4560000340000" for b in results)

    def test_search_by_author_contains(self, client):
        self._seed(client)
        r = client.get("/api/books/search?q=Orwell")
        results = r.get_json()
        assert len(results) >= 2
        assert all("Orwell" in (b["author"] or "") for b in results)

    def test_search_by_title_case_insensitive(self, client):
        """Uses func.lower() under the hood so it works on both SQLite and Postgres."""
        self._seed(client)
        r = client.get("/api/books/search?q=gatsby")  # lowercase query
        results = r.get_json()
        assert any(b["barcode"] == "4560000340000" for b in results)

    def test_search_by_author_case_insensitive(self, client):
        self._seed(client)
        r = client.get("/api/books/search?q=orwell")  # lowercase query
        results = r.get_json()
        assert len(results) >= 2
        assert all("Orwell" in (b["author"] or "") for b in results)

    def test_search_by_mixed_case_title(self, client):
        self._seed(client)
        r = client.get("/api/books/search?q=GATSBY")
        results = r.get_json()
        assert any(b["barcode"] == "4560000340000" for b in results)

    def test_search_wildcard_barcode_prefix(self, client):
        self._seed(client)
        r = client.get("/api/books/search?q=456000034*")
        results = r.get_json()
        assert len(results) == 2
        barcodes = {b["barcode"] for b in results}
        assert "4560000340000" in barcodes
        assert "4560000340001" in barcodes

    def test_search_wildcard_excludes_title_author_matches(self, client):
        """A trailing * suppresses title/author matching (strict barcode mode)."""
        self._seed(client)
        # 'Orwell' with a wildcard — no barcode starts with 'Orwell*' so 0 results
        r = client.get("/api/books/search?q=Orwell*")
        assert r.get_json() == []

    def test_search_respects_limit(self, client):
        self._seed(client)
        r = client.get("/api/books/search?q=*&limit=2")
        assert len(r.get_json()) == 2

    def test_search_bare_star_returns_everything(self, client):
        self._seed(client)
        r = client.get("/api/books/search?q=*")
        assert len(r.get_json()) == 4

    def test_search_returns_archived_books_too(self, client):
        self._seed(client)
        client.post("/api/books/9780451524935/archive")
        r = client.get("/api/books/search?q=Orwell")
        results = r.get_json()
        # Active results should come first
        assert results[0]["is_active"] is True
        # Archived one still appears
        assert any(not b["is_active"] for b in results)

    def test_search_no_match_returns_empty_list(self, client):
        self._seed(client)
        r = client.get("/api/books/search?q=zzznomatch")
        assert r.status_code == 200
        assert r.get_json() == []


# ── GET /api/books/<barcode> ─────────────────────────────────────────────────


class TestGetBook:
    def test_get_book_details(self, client):
        client.post(
            "/api/books/",
            json={"barcode": "9780451524935", "title": "1984", "author": "George Orwell"},
        )
        r = client.get("/api/books/9780451524935")
        assert r.status_code == 200
        data = r.get_json()
        assert data["barcode"] == "9780451524935"
        assert data["title"] == "1984"
        assert data["author"] == "George Orwell"
        assert data["is_active"] is True
        assert data["checked_out"] is False

    def test_get_book_unknown_barcode(self, client):
        r = client.get("/api/books/0000000000")
        assert r.status_code == 400
        assert "Unknown" in r.get_json()["error"]

    def test_get_book_invalid_barcode(self, client):
        r = client.get("/api/books/abc")
        assert r.status_code == 400

    def test_get_book_shows_checked_out_status(self, client, patron):
        client.post(
            "/api/checkouts/",
            json={"card_number": "1234567890", "barcode": "9780451524935", "title": "1984"},
        )
        r = client.get("/api/books/9780451524935")
        assert r.status_code == 200
        data = r.get_json()
        assert data["checked_out"] is True
        assert len(data["active_loans"]) == 1
        loan = data["active_loans"][0]
        assert loan["patron_name"] == "DOE, JANE"
        assert loan["card_number"] == "1234567890"
        assert loan["copies_count"] == 1
        assert len(loan["copies"]) == 1
        assert loan["copies"][0]["due_date"] is not None
        assert data["checked_out_count"] == 1
        assert data["available_copies"] == 0
        assert data["total_copies"] == 1

    def test_get_book_not_checked_out_after_return(self, client, patron):
        client.post(
            "/api/checkouts/",
            json={"card_number": "1234567890", "barcode": "9780451524935"},
        )
        client.post("/api/checkouts/return", json={"barcode": "9780451524935"})
        r = client.get("/api/books/9780451524935")
        data = r.get_json()
        assert data["checked_out"] is False

    def test_get_book_shows_archived_status(self, client):
        client.post("/api/books/", json={"barcode": "9780451524935"})
        client.post("/api/books/9780451524935/archive")
        r = client.get("/api/books/9780451524935")
        assert r.get_json()["is_active"] is False

    def test_get_book_response_includes_required_fields(self, client):
        client.post(
            "/api/books/",
            json={"barcode": "9780451524935", "title": "1984", "category": "book"},
        )
        data = client.get("/api/books/9780451524935").get_json()
        required = {
            "id",
            "barcode",
            "title",
            "author",
            "category",
            "is_active",
            "checked_out",
            "created_at",
            "total_copies",
        }
        assert required.issubset(data.keys())

    def test_get_book_created_at_is_iso(self, client):
        client.post("/api/books/", json={"barcode": "9780451524935"})
        data = client.get("/api/books/9780451524935").get_json()
        assert data["created_at"] is not None
        # ISO 8601 format starts with YYYY-MM-DDThh:mm:ss
        assert len(data["created_at"]) >= 19
        assert data["created_at"][4] == "-" and data["created_at"][10] == "T"


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
        assert data["is_active"] is True

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
