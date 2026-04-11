"""Tests for the checkout service business logic."""

import pytest

from server.app.services import checkout_service
from server.app.services.validators import ValidationError


def test_checkout_creates_record(app, patron):
    co = checkout_service.checkout_item(card="1234567890", barcode="9999999999", category="book")
    assert co.action == "checkout"
    assert co.loan_days == 14  # default is 14 days
    assert co.due_date is not None


def test_checkout_explicit_loan_days(app, patron):
    co = checkout_service.checkout_item(card="1234567890", barcode="9999999999", loan_days=7)
    assert co.loan_days == 7


def test_checkout_dedupes_active(app, patron):
    checkout_service.checkout_item(card="1234567890", barcode="9999999999")
    with pytest.raises(ValidationError, match="already checked out"):
        checkout_service.checkout_item(card="1234567890", barcode="9999999999")


def test_return_clears_active(app, patron):
    checkout_service.checkout_item(card="1234567890", barcode="9999999999")
    checkout_service.return_item("9999999999")
    # Should be re-checkoutable now
    co = checkout_service.checkout_item(card="1234567890", barcode="9999999999")
    assert co.action == "checkout"


def test_return_unknown_item(app, patron):
    with pytest.raises(ValidationError, match="not currently checked out|Unknown"):
        checkout_service.return_item("0000000000")


def test_renew_extends_due_date(app, patron):
    co = checkout_service.checkout_item(card="1234567890", barcode="9999999999")
    original_due = co.due_date
    renewed = checkout_service.renew_item("9999999999", loan_days=21)
    assert original_due is not None
    assert renewed.due_date is not None
    assert renewed.due_date > original_due


def test_summary_counts(app, patron):
    checkout_service.checkout_item(card="1234567890", barcode="1111111111")
    checkout_service.checkout_item(card="1234567890", barcode="2222222222")
    s = checkout_service.patron_summary("1234567890")
    assert s["total_checkouts"] == 2
    assert s["currently_out"] == 2
    assert s["late_count"] == 0


def test_renew_bad_loan_days_returns_400(client, patron):
    client.post("/api/checkouts/", json={"card_number": "1234567890", "barcode": "9999999999"})
    r = client.post(
        "/api/checkouts/renew", json={"barcode": "9999999999", "loan_days": "not-a-number"}
    )
    assert r.status_code == 400
    assert "integer" in r.get_json()["error"]


def test_categories_persisted(app, patron):
    co = checkout_service.checkout_item(card="1234567890", barcode="3333333333", category="dvd")
    assert co.book.category == "dvd"
