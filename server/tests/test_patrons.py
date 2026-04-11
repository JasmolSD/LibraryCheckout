"""Tests for the patron API endpoints."""


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_create_patron(client):
    r = client.post(
        "/api/patrons/",
        json={
            "card_number": "1234567890",
            "name": "doe, jane",
        },
    )
    assert r.status_code == 201
    data = r.get_json()
    assert data["name"] == "DOE, JANE"
    assert data["card_masked"] == "**7890"


def test_create_patron_invalid_card(client):
    r = client.post("/api/patrons/", json={"card_number": "abc", "name": "X"})
    assert r.status_code == 400


def test_get_patron_summary(client, patron):
    r = client.get("/api/patrons/1234567890")
    assert r.status_code == 200
    data = r.get_json()
    assert data["patron"]["name"] == "DOE, JANE"
    assert data["currently_out"] == 0
    assert "history" in data


def test_get_unknown_patron(client):
    r = client.get("/api/patrons/9999999999")
    assert r.status_code == 404


def test_full_checkout_flow_via_api(client, patron):
    # Checkout
    r = client.post(
        "/api/checkouts/",
        json={
            "card_number": "1234567890",
            "barcode": "5555555555",
            "category": "book",
        },
    )
    assert r.status_code == 201

    # Verify summary updated
    summary = client.get("/api/patrons/1234567890").get_json()
    assert summary["currently_out"] == 1

    # Return
    r = client.post("/api/checkouts/return", json={"barcode": "5555555555"})
    assert r.status_code == 200

    summary = client.get("/api/patrons/1234567890").get_json()
    assert summary["currently_out"] == 0
