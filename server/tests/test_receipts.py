"""Tests for the receipt endpoint."""


def test_receipt_invalid_card(client):
    r = client.get("/api/receipts/abc")
    assert r.status_code == 400


def test_receipt_unknown_patron(client):
    r = client.get("/api/receipts/9999999999")
    assert r.status_code == 404


def test_receipt_no_active_checkouts(client, patron):
    r = client.get("/api/receipts/1234567890")
    assert r.status_code == 400
    assert "No active" in r.get_json()["error"]


def test_receipt_returns_pdf(client, patron):
    client.post(
        "/api/checkouts/",
        json={"card_number": "1234567890", "barcode": "5555555555"},
    )
    r = client.get("/api/receipts/1234567890")
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"
    assert len(r.data) > 100  # non-empty PDF


def test_receipt_not_returned_after_return(client, patron):
    client.post("/api/checkouts/", json={"card_number": "1234567890", "barcode": "5555555555"})
    client.post("/api/checkouts/return", json={"barcode": "5555555555"})
    r = client.get("/api/receipts/1234567890")
    assert r.status_code == 400  # no active checkouts left
