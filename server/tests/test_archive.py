"""Tests for patron and book archive/reactivate functionality."""

import pytest

from server.app.models import Transaction
from server.app.services import checkout_service
from server.app.services.validators import ValidationError

# ── Patron archive ───────────────────────────────────────────────────────────


class TestArchivePatron:
    def test_archive_patron(self, app, patron):
        result = checkout_service.archive_patron("1234567890")
        assert not result.is_active

    def test_archive_patron_creates_transaction(self, app, patron):
        checkout_service.archive_patron("1234567890")
        txn = Transaction.query.filter_by(action="archive_patron").first()
        assert txn is not None
        assert txn.patron_id == patron.id
        assert txn.loan_id is None

    def test_archive_patron_with_active_loans_fails(self, app, patron):
        checkout_service.checkout_item(card="1234567890", barcode="9999999999")
        with pytest.raises(ValidationError, match="active loan"):
            checkout_service.archive_patron("1234567890")

    def test_archive_already_archived_fails(self, app, patron):
        checkout_service.archive_patron("1234567890")
        with pytest.raises(ValidationError, match="already archived"):
            checkout_service.archive_patron("1234567890")

    def test_archive_unknown_patron_fails(self, app):
        with pytest.raises(ValidationError, match="not found"):
            checkout_service.archive_patron("9999999999")

    def test_checkout_blocked_for_archived_patron(self, app, patron):
        checkout_service.archive_patron("1234567890")
        with pytest.raises(ValidationError, match="archived"):
            checkout_service.checkout_item(card="1234567890", barcode="9999999999")

    def test_archive_after_return_succeeds(self, app, patron):
        checkout_service.checkout_item(card="1234567890", barcode="9999999999")
        checkout_service.return_item("9999999999")
        result = checkout_service.archive_patron("1234567890")
        assert not result.is_active


class TestReactivatePatron:
    def test_reactivate_patron(self, app, patron):
        checkout_service.archive_patron("1234567890")
        result = checkout_service.reactivate_patron("1234567890")
        assert result.is_active

    def test_reactivate_creates_transaction(self, app, patron):
        checkout_service.archive_patron("1234567890")
        checkout_service.reactivate_patron("1234567890")
        txn = Transaction.query.filter_by(action="reactivate_patron").first()
        assert txn is not None
        assert txn.patron_id == patron.id

    def test_reactivate_already_active_fails(self, app, patron):
        with pytest.raises(ValidationError, match="already active"):
            checkout_service.reactivate_patron("1234567890")

    def test_checkout_works_after_reactivation(self, app, patron):
        checkout_service.archive_patron("1234567890")
        checkout_service.reactivate_patron("1234567890")
        loan = checkout_service.checkout_item(card="1234567890", barcode="9999999999")
        assert loan.is_active


# ── Book archive ─────────────────────────────────────────────────────────────


class TestArchiveBook:
    def test_archive_book(self, app, patron):
        checkout_service.add_book_to_catalog(barcode="9999999999", title="Test")
        result = checkout_service.archive_book("9999999999")
        assert not result.is_active

    def test_archive_book_creates_transaction(self, app, patron):
        book = checkout_service.add_book_to_catalog(barcode="9999999999")
        checkout_service.archive_book("9999999999")
        txn = Transaction.query.filter_by(action="archive_book").first()
        assert txn is not None
        assert txn.book_id == book.id
        assert txn.loan_id is None

    def test_archive_checked_out_book_fails(self, app, patron):
        checkout_service.checkout_item(card="1234567890", barcode="9999999999")
        with pytest.raises(ValidationError, match="currently checked out"):
            checkout_service.archive_book("9999999999")

    def test_archive_already_archived_fails(self, app, patron):
        checkout_service.add_book_to_catalog(barcode="9999999999")
        checkout_service.archive_book("9999999999")
        with pytest.raises(ValidationError, match="already archived"):
            checkout_service.archive_book("9999999999")

    def test_archive_unknown_book_fails(self, app):
        with pytest.raises(ValidationError, match="Unknown"):
            checkout_service.archive_book("0000000000")

    def test_checkout_blocked_for_archived_book(self, app, patron):
        checkout_service.add_book_to_catalog(barcode="9999999999")
        checkout_service.archive_book("9999999999")
        with pytest.raises(ValidationError, match="archived"):
            checkout_service.checkout_item(card="1234567890", barcode="9999999999")

    def test_archive_after_return_succeeds(self, app, patron):
        checkout_service.checkout_item(card="1234567890", barcode="9999999999")
        checkout_service.return_item("9999999999")
        result = checkout_service.archive_book("9999999999")
        assert not result.is_active


class TestReactivateBook:
    def test_reactivate_book(self, app, patron):
        checkout_service.add_book_to_catalog(barcode="9999999999")
        checkout_service.archive_book("9999999999")
        result = checkout_service.reactivate_book("9999999999")
        assert result.is_active

    def test_reactivate_creates_transaction(self, app, patron):
        book = checkout_service.add_book_to_catalog(barcode="9999999999")
        checkout_service.archive_book("9999999999")
        checkout_service.reactivate_book("9999999999")
        txn = Transaction.query.filter_by(action="reactivate_book").first()
        assert txn is not None
        assert txn.book_id == book.id

    def test_reactivate_already_active_fails(self, app, patron):
        checkout_service.add_book_to_catalog(barcode="9999999999")
        with pytest.raises(ValidationError, match="already active"):
            checkout_service.reactivate_book("9999999999")

    def test_checkout_works_after_reactivation(self, app, patron):
        checkout_service.add_book_to_catalog(barcode="9999999999")
        checkout_service.archive_book("9999999999")
        checkout_service.reactivate_book("9999999999")
        loan = checkout_service.checkout_item(card="1234567890", barcode="9999999999")
        assert loan.is_active


# ── API endpoint tests ───────────────────────────────────────────────────────


class TestArchivePatronAPI:
    def test_archive_via_api(self, client, patron):
        r = client.post("/api/patrons/1234567890/archive")
        assert r.status_code == 200
        assert r.get_json()["is_active"] is False

    def test_reactivate_via_api(self, client, patron):
        client.post("/api/patrons/1234567890/archive")
        r = client.post("/api/patrons/1234567890/reactivate")
        assert r.status_code == 200
        assert r.get_json()["is_active"] is True

    def test_archive_with_active_loan_returns_400(self, client, patron):
        client.post(
            "/api/checkouts/",
            json={"card_number": "1234567890", "barcode": "9999999999"},
        )
        r = client.post("/api/patrons/1234567890/archive")
        assert r.status_code == 400
        assert "active loan" in r.get_json()["error"]

    def test_patron_summary_shows_is_active(self, client, patron):
        r = client.get("/api/patrons/1234567890")
        assert r.get_json()["patron"]["is_active"] is True

        client.post("/api/patrons/1234567890/archive")
        r = client.get("/api/patrons/1234567890")
        assert r.get_json()["patron"]["is_active"] is False

    def test_archive_shows_in_history(self, client, patron):
        client.post("/api/patrons/1234567890/archive")
        r = client.get("/api/patrons/1234567890")
        history = r.get_json()["history"]
        assert any(h["action"] == "archive_patron" for h in history)


class TestArchiveBookAPI:
    def test_archive_via_api(self, client):
        client.post("/api/books/", json={"barcode": "9999999999", "title": "Test"})
        r = client.post("/api/books/9999999999/archive")
        assert r.status_code == 200
        assert r.get_json()["is_active"] is False

    def test_reactivate_via_api(self, client):
        client.post("/api/books/", json={"barcode": "9999999999"})
        client.post("/api/books/9999999999/archive")
        r = client.post("/api/books/9999999999/reactivate")
        assert r.status_code == 200
        assert r.get_json()["is_active"] is True

    def test_archive_checked_out_book_returns_400(self, client, patron):
        client.post(
            "/api/checkouts/",
            json={"card_number": "1234567890", "barcode": "9999999999"},
        )
        r = client.post("/api/books/9999999999/archive")
        assert r.status_code == 400
        assert "checked out" in r.get_json()["error"]
