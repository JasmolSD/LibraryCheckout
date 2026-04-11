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
    assert data["is_active"] is True


def test_create_patron_invalid_card(client):
    r = client.post(
        "/api/patrons/",
        json={
            "card_number": "abc",
            "first_name": "X",
            "last_name": "Y",
            "birth_date": "1990-01-01",
        },
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


def test_checkout_response_is_loan_shape(client, patron):
    """Checkout response returns a Loan dict, not the old Checkout shape."""
    r = client.post(
        "/api/checkouts/",
        json={"card_number": "1234567890", "barcode": "5555555555"},
    )
    assert r.status_code == 201
    data = r.get_json()
    # Loan fields present
    assert "loan_days" in data
    assert "checked_out_at" in data
    assert "due_date" in data
    assert "is_active" in data
    assert "is_late" in data
    assert "barcode" in data
    # Old Checkout-only field absent
    assert "action" not in data


def test_return_response_is_loan_shape(client, patron):
    """Return response returns the updated Loan dict."""
    client.post(
        "/api/checkouts/",
        json={"card_number": "1234567890", "barcode": "5555555555"},
    )
    r = client.post("/api/checkouts/return", json={"barcode": "5555555555"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["returned_at"] is not None
    assert data["is_active"] is False
    assert "action" not in data


def test_patron_summary_history_has_action_field(client, patron):
    """History entries come from Transaction, which includes the action field."""
    client.post(
        "/api/checkouts/",
        json={"card_number": "1234567890", "barcode": "5555555555"},
    )
    summary = client.get("/api/patrons/1234567890").get_json()
    assert len(summary["history"]) >= 1
    assert summary["history"][0]["action"] == "checkout"


def test_manual_return_from_patron_active_items(client, patron):
    """Simulate manual return: look up patron, see active items, return one."""
    # Checkout two items
    client.post(
        "/api/checkouts/",
        json={"card_number": "1234567890", "barcode": "5555555555"},
    )
    client.post(
        "/api/checkouts/",
        json={"card_number": "1234567890", "barcode": "6666666666"},
    )

    # Look up patron — should show 2 active items
    summary = client.get("/api/patrons/1234567890").get_json()
    assert summary["currently_out"] == 2

    # Return one item by barcode (as a librarian would from the UI)
    r = client.post("/api/checkouts/return", json={"barcode": "5555555555"})
    assert r.status_code == 200

    # Verify only 1 remains
    summary = client.get("/api/patrons/1234567890").get_json()
    assert summary["currently_out"] == 1
    barcodes = [item["barcode"] for item in summary["active_items"]]
    assert "5555555555" not in barcodes
    assert "6666666666" in barcodes


def test_books_page_returns_200(client):
    """The /books page route responds successfully."""
    r = client.get("/books")
    assert r.status_code == 200
