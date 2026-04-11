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
            "first_name": "Jane",
            "last_name": "Doe",
            "birth_date": "1990-01-15",
        },
    )
    assert r.status_code == 201
    data = r.get_json()
    assert data["name"] == "DOE, JANE"
    assert data["card_masked"] == "**7890"


def test_create_patron_invalid_card(client):
    r = client.post(
        "/api/patrons/",
        json={"card_number": "abc", "first_name": "X", "last_name": "Y", "birth_date": "1990-01-01"},
    )
    assert r.status_code == 400


def test_create_patron_missing_first_name(client):
    r = client.post(
        "/api/patrons/",
        json={"card_number": "1234567890", "last_name": "Doe", "birth_date": "1990-01-15"},
    )
    assert r.status_code == 400
    assert "first name" in r.get_json()["error"].lower()


def test_create_patron_missing_last_name(client):
    r = client.post(
        "/api/patrons/",
        json={"card_number": "1234567890", "first_name": "Jane", "birth_date": "1990-01-15"},
    )
    assert r.status_code == 400
    assert "last name" in r.get_json()["error"].lower()


def test_create_patron_missing_birth_date(client):
    r = client.post(
        "/api/patrons/",
        json={"card_number": "1234567890", "first_name": "Jane", "last_name": "Doe"},
    )
    assert r.status_code == 400
    assert "birth date" in r.get_json()["error"].lower()


def test_create_patron_invalid_birth_date(client):
    r = client.post(
        "/api/patrons/",
        json={
            "card_number": "1234567890",
            "first_name": "Jane",
            "last_name": "Doe",
            "birth_date": "not-a-date",
        },
    )
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


def test_create_patron_returns_existing(client, patron):
    """Posting the same card twice returns the existing patron unchanged."""
    r = client.post(
        "/api/patrons/",
        json={
            "card_number": "1234567890",
            "first_name": "Different",
            "last_name": "Name",
            "birth_date": "2000-01-01",
        },
    )
    assert r.status_code == 201
    assert r.get_json()["name"] == "DOE, JANE"


def test_search_patron_by_name(client, patron):
    r = client.get("/api/patrons/search?q=doe")
    assert r.status_code == 200
    results = r.get_json()
    assert len(results) >= 1
    assert any(p["last_name"] == "DOE" for p in results)


def test_search_patron_by_first_name(client, patron):
    r = client.get("/api/patrons/search?q=jane")
    assert r.status_code == 200
    results = r.get_json()
    assert len(results) >= 1
    assert any(p["first_name"] == "JANE" for p in results)


def test_search_patron_empty_query(client):
    r = client.get("/api/patrons/search?q=")
    assert r.status_code == 400


def test_search_patron_no_results(client, patron):
    r = client.get("/api/patrons/search?q=zzznomatch")
    assert r.status_code == 200
    assert r.get_json() == []


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
