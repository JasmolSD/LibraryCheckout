"""Tests for the checkout service business logic."""

import pytest

from server.app.services import checkout_service
from server.app.services.validators import ValidationError


def test_checkout_creates_record(app, patron):
    loan = checkout_service.checkout_item(card="1234567890", barcode="9999999999", category="book")
    assert loan.returned_at is None  # active loan
    assert loan.loan_days == 14  # default is 14 days
    assert loan.due_date is not None


def test_checkout_creates_transaction(app, patron):
    loan = checkout_service.checkout_item(card="1234567890", barcode="9999999999")
    assert len(loan.transactions) == 1
    assert loan.transactions[0].action == "checkout"


def test_checkout_explicit_loan_days(app, patron):
    loan = checkout_service.checkout_item(card="1234567890", barcode="9999999999", loan_days=7)
    assert loan.loan_days == 7


def test_checkout_dedupes_active(app, patron):
    checkout_service.checkout_item(card="1234567890", barcode="9999999999")
    with pytest.raises(ValidationError, match="already checked out"):
        checkout_service.checkout_item(card="1234567890", barcode="9999999999")


def test_return_clears_active(app, patron):
    checkout_service.checkout_item(card="1234567890", barcode="9999999999")
    checkout_service.return_item("9999999999")
    # Should be re-checkoutable now
    loan = checkout_service.checkout_item(card="1234567890", barcode="9999999999")
    assert loan.is_active


def test_return_sets_returned_at(app, patron):
    checkout_service.checkout_item(card="1234567890", barcode="9999999999")
    returned = checkout_service.return_item("9999999999")
    assert returned.returned_at is not None
    assert not returned.is_active


def test_return_creates_transaction(app, patron):
    loan = checkout_service.checkout_item(card="1234567890", barcode="9999999999")
    checkout_service.return_item("9999999999")
    # Loan should now have 2 transactions: checkout + return
    assert len(loan.transactions) == 2
    actions = [t.action for t in loan.transactions]
    assert "checkout" in actions
    assert "return" in actions


def test_return_unknown_item(app, patron):
    with pytest.raises(ValidationError, match="not currently checked out|Unknown"):
        checkout_service.return_item("0000000000")


def test_renew_extends_due_date(app, patron):
    loan = checkout_service.checkout_item(card="1234567890", barcode="9999999999")
    original_due = loan.due_date
    renewed = checkout_service.renew_item("9999999999", loan_days=21)
    assert original_due is not None
    assert renewed.due_date is not None
    assert renewed.due_date > original_due


def test_renew_creates_transaction(app, patron):
    loan = checkout_service.checkout_item(card="1234567890", barcode="9999999999")
    checkout_service.renew_item("9999999999", loan_days=21)
    assert len(loan.transactions) == 2
    actions = [t.action for t in loan.transactions]
    assert "renew" in actions


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
    loan = checkout_service.checkout_item(card="1234567890", barcode="3333333333", category="dvd")
    assert loan.book.category == "dvd"
