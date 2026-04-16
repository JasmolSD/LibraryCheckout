"""Tests for book quantity tracking and multi-copy checkouts."""

from datetime import date

import pytest

from server.app.services import checkout_service
from server.app.services.validators import ValidationError


@pytest.fixture
def patron2(app):
    """A second patron so multi-patron checkout scenarios work."""
    return checkout_service.get_or_create_patron(
        card="9999999999",
        first_name="BOB",
        last_name="SMITH",
        birth_date=date(1985, 6, 15),
    )


# ── Adding books with quantity ───────────────────────────────────────────────


class TestAddQuantity:
    def test_add_book_default_quantity(self, app):
        book = checkout_service.add_book_to_catalog(barcode="9780451524935", title="1984")
        assert book.total_copies == 1
        assert book.available_copies == 1
        assert book.checked_out_count == 0

    def test_add_book_explicit_quantity(self, app):
        book = checkout_service.add_book_to_catalog(
            barcode="9780451524935", title="1984", quantity=5
        )
        assert book.total_copies == 5
        assert book.available_copies == 5

    def test_add_book_zero_quantity_rejected(self, app):
        with pytest.raises(ValidationError, match="at least 1"):
            checkout_service.add_book_to_catalog(barcode="9780451524935", quantity=0)

    def test_add_book_negative_quantity_rejected(self, app):
        with pytest.raises(ValidationError, match="at least 1"):
            checkout_service.add_book_to_catalog(barcode="9780451524935", quantity=-3)

    def test_add_book_via_api_with_quantity(self, client):
        r = client.post(
            "/api/books/",
            json={"barcode": "9780451524935", "title": "1984", "quantity": 3},
        )
        assert r.status_code == 201
        data = r.get_json()
        assert data["total_copies"] == 3
        assert data["available_copies"] == 3

    def test_add_book_api_rejects_non_integer_quantity(self, client):
        r = client.post(
            "/api/books/",
            json={"barcode": "9780451524935", "quantity": "five"},
        )
        assert r.status_code == 400


# ── Updating quantity ────────────────────────────────────────────────────────


class TestUpdateQuantity:
    def test_update_increases_total(self, app):
        checkout_service.add_book_to_catalog(barcode="9780451524935", quantity=2)
        book = checkout_service.update_book_quantity("9780451524935", 5)
        assert book.total_copies == 5
        assert book.available_copies == 5

    def test_update_decreases_total(self, app):
        checkout_service.add_book_to_catalog(barcode="9780451524935", quantity=5)
        book = checkout_service.update_book_quantity("9780451524935", 2)
        assert book.total_copies == 2

    def test_update_below_checked_out_fails(self, app, patron):
        checkout_service.add_book_to_catalog(barcode="9780451524935", quantity=3)
        checkout_service.checkout_item(card="1234567890", barcode="9780451524935")
        with pytest.raises(ValidationError, match="currently checked out"):
            checkout_service.update_book_quantity("9780451524935", 0)

    def test_update_negative_fails(self, app):
        checkout_service.add_book_to_catalog(barcode="9780451524935", quantity=3)
        with pytest.raises(ValidationError, match="cannot be negative"):
            checkout_service.update_book_quantity("9780451524935", -1)

    def test_update_unknown_book_fails(self, app):
        with pytest.raises(ValidationError, match="Unknown"):
            checkout_service.update_book_quantity("9780451524935", 5)

    def test_update_via_api(self, client):
        client.post("/api/books/", json={"barcode": "9780451524935", "quantity": 1})
        r = client.post("/api/books/9780451524935/quantity", json={"total_copies": 4})
        assert r.status_code == 200
        assert r.get_json()["total_copies"] == 4

    def test_update_api_rejects_non_integer(self, client):
        client.post("/api/books/", json={"barcode": "9780451524935"})
        r = client.post("/api/books/9780451524935/quantity", json={"total_copies": "ten"})
        assert r.status_code == 400


# ── Multi-copy checkouts ─────────────────────────────────────────────────────


class TestMultiCopyCheckout:
    def test_multiple_patrons_can_checkout_same_book(self, app, patron, patron2):
        checkout_service.add_book_to_catalog(barcode="9780451524935", quantity=2)
        checkout_service.checkout_item(card="1234567890", barcode="9780451524935")
        checkout_service.checkout_item(card="9999999999", barcode="9780451524935")
        details = checkout_service.book_details("9780451524935")
        assert details["checked_out_count"] == 2
        assert details["available_copies"] == 0

    def test_same_patron_can_hold_multiple_copies(self, app, patron):
        checkout_service.add_book_to_catalog(barcode="9780451524935", quantity=3)
        checkout_service.checkout_item(card="1234567890", barcode="9780451524935")
        checkout_service.checkout_item(card="1234567890", barcode="9780451524935")
        details = checkout_service.book_details("9780451524935")
        assert details["checked_out_count"] == 2
        assert details["available_copies"] == 1
        # Aggregated into a single patron entry
        assert len(details["active_loans"]) == 1
        assert details["active_loans"][0]["copies_count"] == 2

    def test_checkout_blocked_when_inventory_exhausted(self, app, patron, patron2):
        checkout_service.add_book_to_catalog(barcode="9780451524935", quantity=1)
        checkout_service.checkout_item(card="1234567890", barcode="9780451524935")
        with pytest.raises(ValidationError, match="No copies"):
            checkout_service.checkout_item(card="9999999999", barcode="9780451524935")

    def test_available_count_updates_on_checkout(self, app, patron):
        checkout_service.add_book_to_catalog(barcode="9780451524935", quantity=3)
        assert checkout_service.book_details("9780451524935")["available_copies"] == 3
        checkout_service.checkout_item(card="1234567890", barcode="9780451524935")
        assert checkout_service.book_details("9780451524935")["available_copies"] == 2

    def test_return_frees_inventory(self, app, patron):
        checkout_service.add_book_to_catalog(barcode="9780451524935", quantity=2)
        checkout_service.checkout_item(card="1234567890", barcode="9780451524935")
        assert checkout_service.book_details("9780451524935")["available_copies"] == 1
        checkout_service.return_item("9780451524935")
        assert checkout_service.book_details("9780451524935")["available_copies"] == 2


# ── Targeted return (by patron card) ─────────────────────────────────────────


class TestTargetedReturn:
    def test_return_by_card_targets_specific_patron(self, app, patron, patron2):
        checkout_service.add_book_to_catalog(barcode="9780451524935", quantity=2)
        checkout_service.checkout_item(card="1234567890", barcode="9780451524935")
        checkout_service.checkout_item(card="9999999999", barcode="9780451524935")

        # Return the second patron's copy specifically
        checkout_service.return_item("9780451524935", card="9999999999")

        details = checkout_service.book_details("9780451524935")
        assert details["checked_out_count"] == 1
        assert details["active_loans"][0]["card_number"] == "1234567890"

    def test_return_by_card_returns_one_copy_when_multi(self, app, patron):
        """When a patron holds multiple copies, return_item returns one at a time."""
        checkout_service.add_book_to_catalog(barcode="9780451524935", quantity=3)
        checkout_service.checkout_item(card="1234567890", barcode="9780451524935")
        checkout_service.checkout_item(card="1234567890", barcode="9780451524935")
        checkout_service.return_item("9780451524935", card="1234567890")
        details = checkout_service.book_details("9780451524935")
        assert details["checked_out_count"] == 1
        assert details["active_loans"][0]["copies_count"] == 1

    def test_return_by_card_unknown_patron_fails(self, app, patron):
        checkout_service.add_book_to_catalog(barcode="9780451524935", quantity=1)
        checkout_service.checkout_item(card="1234567890", barcode="9780451524935")
        with pytest.raises(ValidationError, match="Patron not found"):
            checkout_service.return_item("9780451524935", card="8888888888")

    def test_return_via_api_with_card_number(self, client, patron):
        # Register a second patron
        client.post(
            "/api/patrons/",
            json={
                "card_number": "9999999999",
                "first_name": "Bob",
                "last_name": "Smith",
                "birth_date": "1985-06-15",
            },
        )
        client.post("/api/books/", json={"barcode": "9780451524935", "quantity": 2})
        client.post(
            "/api/checkouts/",
            json={"card_number": "1234567890", "barcode": "9780451524935"},
        )
        client.post(
            "/api/checkouts/",
            json={"card_number": "9999999999", "barcode": "9780451524935"},
        )
        r = client.post(
            "/api/checkouts/return",
            json={"barcode": "9780451524935", "card_number": "9999999999"},
        )
        assert r.status_code == 200
        details = client.get("/api/books/9780451524935").get_json()
        assert details["active_loans"][0]["card_number"] == "1234567890"


# ── book_details aggregation ─────────────────────────────────────────────────


class TestBookDetailsAggregation:
    def test_inventory_fields_present(self, client):
        client.post("/api/books/", json={"barcode": "9780451524935", "quantity": 5})
        data = client.get("/api/books/9780451524935").get_json()
        assert data["total_copies"] == 5
        assert data["available_copies"] == 5
        assert data["checked_out_count"] == 0
        assert data["active_loans"] == []

    def test_aggregated_by_patron(self, client, patron):
        client.post("/api/books/", json={"barcode": "9780451524935", "quantity": 3})
        client.post(
            "/api/checkouts/",
            json={"card_number": "1234567890", "barcode": "9780451524935"},
        )
        client.post(
            "/api/checkouts/",
            json={"card_number": "1234567890", "barcode": "9780451524935"},
        )
        data = client.get("/api/books/9780451524935").get_json()
        assert len(data["active_loans"]) == 1
        assert data["active_loans"][0]["copies_count"] == 2
        assert len(data["active_loans"][0]["copies"]) == 2
