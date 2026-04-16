"""Tests for: patron card prefix search, PATCH /api/patrons/<card>,
patron-card PDF, and the SMTP-backed email flows (patched out).
"""

from unittest.mock import patch

import pytest

from server.app.services import checkout_service
from server.app.services.validators import ValidationError

# ── search_patrons now matches card prefix ────────────────────────────────────


class TestPatronSearchByCard:
    def test_search_by_full_card(self, client, patron):
        r = client.get("/api/patrons/search?q=1234567890")
        assert r.status_code == 200
        results = r.get_json()
        assert len(results) == 1
        assert results[0]["card_number"] == "1234567890"

    def test_search_by_card_prefix(self, client, patron):
        r = client.get("/api/patrons/search?q=12345")
        results = r.get_json()
        assert any(p["card_number"] == "1234567890" for p in results)

    def test_search_still_matches_name(self, client, patron):
        r = client.get("/api/patrons/search?q=DOE")
        results = r.get_json()
        assert any(p["last_name"] == "DOE" for p in results)

    def test_search_name_and_card_dont_collide(self, client, patron):
        """A query that matches neither names nor any card prefix returns []."""
        r = client.get("/api/patrons/search?q=zzznomatch")
        assert r.get_json() == []


# ── PATCH /api/patrons/<card> ────────────────────────────────────────────────


class TestUpdatePatron:
    def test_update_email_and_phone(self, client, patron):
        r = client.patch(
            "/api/patrons/1234567890",
            json={"email": "jane@example.com", "phone": "555-1234"},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["email"] == "jane@example.com"
        assert data["phone"] == "555-1234"

    def test_update_clears_optional_fields_with_empty_string(self, client, patron):
        client.patch("/api/patrons/1234567890", json={"email": "x@y.z", "phone": "999"})
        r = client.patch("/api/patrons/1234567890", json={"email": "", "phone": ""})
        data = r.get_json()
        assert data["email"] is None
        assert data["phone"] is None

    def test_update_names_uppercased(self, client, patron):
        r = client.patch(
            "/api/patrons/1234567890",
            json={"first_name": "alice", "last_name": "smith"},
        )
        data = r.get_json()
        assert data["first_name"] == "ALICE"
        assert data["last_name"] == "SMITH"

    def test_update_blank_first_name_rejected(self, client, patron):
        r = client.patch("/api/patrons/1234567890", json={"first_name": "   "})
        assert r.status_code == 400
        assert "first name" in r.get_json()["error"].lower()

    def test_update_blank_last_name_rejected(self, client, patron):
        r = client.patch("/api/patrons/1234567890", json={"last_name": ""})
        assert r.status_code == 400

    def test_update_bad_birth_date_rejected(self, client, patron):
        r = client.patch("/api/patrons/1234567890", json={"birth_date": "not-a-date"})
        assert r.status_code == 400

    def test_update_unknown_patron_returns_404(self, client):
        r = client.patch("/api/patrons/9999999999", json={"email": "x@y.z"})
        assert r.status_code == 404

    def test_update_partial(self, client, patron):
        """Unspecified fields remain unchanged."""
        r = client.patch("/api/patrons/1234567890", json={"email": "new@x.com"})
        data = r.get_json()
        assert data["email"] == "new@x.com"
        assert data["first_name"] == "JANE"  # untouched
        assert data["last_name"] == "DOE"


# ── GET /api/patrons/<card>/card-pdf ─────────────────────────────────────────


class TestPatronCardPdf:
    def test_returns_pdf(self, client, patron):
        r = client.get("/api/patrons/1234567890/card-pdf")
        assert r.status_code == 200
        assert r.mimetype == "application/pdf"
        assert len(r.data) > 500  # non-empty PDF
        # PDF files start with %PDF-
        assert r.data[:5] == b"%PDF-"

    def test_unknown_patron_404(self, client):
        r = client.get("/api/patrons/9999999999/card-pdf")
        assert r.status_code == 404

    def test_invalid_card_400(self, client):
        r = client.get("/api/patrons/abc/card-pdf")
        assert r.status_code == 400


# ── Email endpoints (SMTP patched out) ───────────────────────────────────────


class TestEmailEndpoints:
    def test_email_disabled_by_default(self, client, patron):
        """With SMTP_HOST empty (the default in TestConfig), both email
        endpoints should return 503."""
        client.patch("/api/patrons/1234567890", json={"email": "jane@example.com"})
        r = client.post("/api/patrons/1234567890/card-email")
        assert r.status_code == 503
        assert "not configured" in r.get_json()["error"].lower()

    def test_email_card_requires_email_on_file(self, client, patron):
        """Even with SMTP configured, a patron without an email gets a 400."""
        with patch.dict(
            client.application.config,
            {"SMTP_HOST": "smtp.example.com"},
            clear=False,
        ):
            r = client.post("/api/patrons/1234567890/card-email")
            assert r.status_code == 400
            assert "no email" in r.get_json()["error"].lower()

    def test_email_card_sends_with_mock_smtp(self, client, patron):
        client.patch("/api/patrons/1234567890", json={"email": "jane@example.com"})
        with (
            patch.dict(
                client.application.config,
                {"SMTP_HOST": "smtp.example.com", "SMTP_FROM": "lib@example.com"},
                clear=False,
            ),
            patch("smtplib.SMTP") as mock_smtp,
        ):
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            r = client.post("/api/patrons/1234567890/card-email")
            assert r.status_code == 200
            assert r.get_json()["sent"] is True
            assert r.get_json()["to"] == "jane@example.com"
            assert mock_smtp.return_value.send_message.called

    def test_email_receipt_requires_active_checkouts(self, client, patron):
        client.patch("/api/patrons/1234567890", json={"email": "jane@example.com"})
        with patch.dict(
            client.application.config,
            {"SMTP_HOST": "smtp.example.com"},
            clear=False,
        ):
            r = client.post("/api/receipts/1234567890/email")
            assert r.status_code == 400
            assert "no active" in r.get_json()["error"].lower()

    def test_email_receipt_sends_with_mock_smtp(self, client, patron):
        client.patch("/api/patrons/1234567890", json={"email": "jane@example.com"})
        client.post(
            "/api/checkouts/",
            json={"card_number": "1234567890", "barcode": "9780451524935"},
        )
        with (
            patch.dict(
                client.application.config,
                {"SMTP_HOST": "smtp.example.com", "SMTP_FROM": "lib@example.com"},
                clear=False,
            ),
            patch("smtplib.SMTP") as mock_smtp,
        ):
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            r = client.post("/api/receipts/1234567890/email")
            assert r.status_code == 200
            assert r.get_json()["sent"] is True
            assert r.get_json()["count"] == 1
            assert mock_smtp.return_value.send_message.called


# ── Service-level update_patron ──────────────────────────────────────────────


class TestUpdatePatronService:
    def test_update_partial_keeps_other_fields(self, app, patron):
        p = checkout_service.update_patron("1234567890", email="a@b.com")
        assert p.email == "a@b.com"
        assert p.first_name == "JANE"

    def test_clearing_middle_name(self, app, patron):
        checkout_service.update_patron("1234567890", middle_name="Marie")
        p = checkout_service.update_patron("1234567890", middle_name="")
        assert p.middle_name is None

    def test_blank_first_name_raises(self, app, patron):
        with pytest.raises(ValidationError, match="First name"):
            checkout_service.update_patron("1234567890", first_name="   ")

    def test_unknown_patron_raises(self, app):
        with pytest.raises(ValidationError, match="not found"):
            checkout_service.update_patron("9999999999", email="x@y.z")
