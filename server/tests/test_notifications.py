"""Tests for the automatic archival notification emails.

Every test here runs ``send_notification_email`` synchronously (via a
patch that replaces ``threading.Thread`` with a shim that invokes the
worker in-process) so assertions are deterministic.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from server.app.services import checkout_service, email_service


class _ImmediateThread:
    """Stand-in for ``threading.Thread`` that runs the target inline.

    Lets us assert on calls without racing a background daemon thread.
    """

    def __init__(self, target=None, daemon=None, **_ignored):
        self._target = target

    def start(self):
        if self._target:
            self._target()


@pytest.fixture
def sync_threads():
    """Patch threading.Thread so notifications send synchronously."""
    with patch.object(email_service.threading, "Thread", _ImmediateThread):
        yield


@pytest.fixture
def enabled(client):
    """Configure the Flask app with fake SMTP so notifications actually fire."""
    with patch.dict(
        client.application.config,
        {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": 587,
            "SMTP_USER": "library@example.com",
            "SMTP_PASSWORD": "app-password",
            "SMTP_FROM": "library@example.com",
            "SMTP_USE_TLS": True,
            "ARCHIVE_NOTIFICATIONS_ENABLED": True,
        },
        clear=False,
    ):
        yield


@pytest.fixture
def patron_email_enabled(client):
    """Configure SMTP and enable patron-facing action emails only."""
    with patch.dict(
        client.application.config,
        {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": 587,
            "SMTP_USER": "library@example.com",
            "SMTP_PASSWORD": "app-password",
            "SMTP_FROM": "library@example.com",
            "SMTP_USE_TLS": True,
            "NOTIFY_PATRONS_ON_ACTION": True,
            # Keep archive notifications off so assertions count
            # only the patron-facing email.
            "ARCHIVE_NOTIFICATIONS_ENABLED": False,
        },
        clear=False,
    ):
        yield


# ── Kill-switch and gating ───────────────────────────────────────────────────


class TestNotificationGating:
    def test_noop_when_smtp_not_configured(self, client, sync_threads):
        """With TestConfig's empty SMTP_HOST, no SMTP call should happen."""
        with patch("smtplib.SMTP") as mock_smtp:
            email_service.send_notification_email(subject="ignored", body="ignored", folder="Nope")
            assert not mock_smtp.called

    def test_noop_when_flag_disabled(self, client, sync_threads):
        with (
            patch.dict(
                client.application.config,
                {"SMTP_HOST": "smtp.example.com", "ARCHIVE_NOTIFICATIONS_ENABLED": False},
                clear=False,
            ),
            patch("smtplib.SMTP") as mock_smtp,
        ):
            email_service.send_notification_email(subject="ignored", body="ignored")
            assert not mock_smtp.called

    def test_sends_when_flag_enabled(self, client, sync_threads, enabled):
        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            email_service.send_notification_email(subject="Test", body="Body", folder=None)
            assert mock_smtp.return_value.send_message.called

    def test_smtp_failure_is_swallowed(self, client, sync_threads, enabled):
        """Notification emails must never raise into the caller."""
        with patch("smtplib.SMTP", side_effect=RuntimeError("boom")):
            # Must not raise
            email_service.send_notification_email(subject="x", body="y")


# ── IMAP APPEND is attempted when configured ─────────────────────────────────


class TestImapArchive:
    def test_no_imap_when_host_empty(self, client, sync_threads, enabled):
        """Without IMAP_HOST, no IMAP session is opened."""
        with patch("smtplib.SMTP") as mock_smtp, patch("imaplib.IMAP4_SSL") as mock_imap:
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            email_service.send_notification_email(subject="x", body="y", folder="Library Receipts")
            assert not mock_imap.called

    def test_imap_append_when_host_set(self, client, sync_threads, enabled):
        with (
            patch.dict(
                client.application.config,
                {
                    "IMAP_HOST": "imap.example.com",
                    "IMAP_PORT": 993,
                    "IMAP_USE_SSL": True,
                },
                clear=False,
            ),
            patch("smtplib.SMTP") as mock_smtp,
            patch("imaplib.IMAP4_SSL") as mock_imap,
        ):
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            mock_imap.return_value = MagicMock()

            email_service.send_notification_email(subject="x", body="y", folder="Library Receipts")

            assert mock_imap.called
            imap_instance = mock_imap.return_value
            imap_instance.login.assert_called_once_with("library@example.com", "app-password")
            imap_instance.append.assert_called_once()
            # First positional arg is the quoted folder name
            assert imap_instance.append.call_args[0][0] == '"Library Receipts"'

    def test_imap_failure_does_not_break_smtp(self, client, sync_threads, enabled):
        """IMAP errors are logged but the SMTP send still counts as successful."""
        with (
            patch.dict(
                client.application.config,
                {"IMAP_HOST": "imap.example.com", "IMAP_USE_SSL": True},
                clear=False,
            ),
            patch("smtplib.SMTP") as mock_smtp,
            patch("imaplib.IMAP4_SSL", side_effect=RuntimeError("imap down")),
        ):
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            email_service.send_notification_email(subject="x", body="y", folder="Library Receipts")
            # SMTP still went through
            assert mock_smtp.return_value.send_message.called


# ── Service-level hooks wire through correctly ──────────────────────────────


class TestServiceHooks:
    def test_checkout_triggers_notification(self, client, patron, sync_threads, enabled):
        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            checkout_service.checkout_item(card="1234567890", barcode="9780451524935", title="1984")
            sent = mock_smtp.return_value.send_message.call_args_list
            assert len(sent) == 1
            msg = sent[0][0][0]  # the EmailMessage argument
            assert "[Library Receipt]" in msg["Subject"]
            assert "1984" in msg["Subject"]
            assert msg["From"] == "library@example.com"
            assert msg["To"] == "library@example.com"
            body = msg.get_content()
            assert "9780451524935" in body
            assert "DOE, JANE" in body

    def test_new_patron_registration_triggers_notification(self, client, sync_threads, enabled):
        from datetime import date

        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            checkout_service.get_or_create_patron(
                card="1234567890",
                first_name="Jane",
                last_name="Doe",
                birth_date=date(1990, 1, 15),
            )
            sent = mock_smtp.return_value.send_message.call_args_list
            assert len(sent) == 1
            msg = sent[0][0][0]
            assert "[Library Patron] New" in msg["Subject"]
            assert "1234567890" in msg["Subject"]
            body = msg.get_content()
            assert "DOE, JANE" in body

    def test_existing_patron_lookup_does_not_trigger_notification(
        self, client, patron, sync_threads, enabled
    ):
        """Calling get_or_create_patron for an existing card is just a read."""
        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            checkout_service.get_or_create_patron(card="1234567890")
            assert not mock_smtp.return_value.send_message.called

    def test_patron_update_with_changes_triggers_notification(
        self, client, patron, sync_threads, enabled
    ):
        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            checkout_service.update_patron("1234567890", email="jane@example.com")
            sent = mock_smtp.return_value.send_message.call_args_list
            assert len(sent) == 1
            msg = sent[0][0][0]
            assert "[Library Patron] Updated" in msg["Subject"]
            body = msg.get_content()
            assert "email" in body  # Shows up in the diff block
            assert "jane@example.com" in body

    def test_patron_update_no_changes_does_not_trigger_notification(
        self, client, patron, sync_threads, enabled
    ):
        """A no-op save (same values as before) should be silent."""
        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            # Passing the current values — no actual change
            checkout_service.update_patron("1234567890", first_name="Jane", last_name="Doe")
            assert not mock_smtp.return_value.send_message.called

    def test_checkout_notification_does_not_break_checkout_on_smtp_error(
        self, client, patron, sync_threads, enabled
    ):
        """If SMTP blows up, the checkout itself must still succeed."""
        with patch("smtplib.SMTP", side_effect=RuntimeError("smtp down")):
            loan = checkout_service.checkout_item(card="1234567890", barcode="9780451524935")
            assert loan.id is not None
            assert loan.is_active


# ── Patron-facing confirmation emails (checkout / renew / return) ───────────


def _text_body(msg):
    """Extract the plain-text body from a possibly-multipart EmailMessage."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_content()
        return ""
    return msg.get_content()


def _pdf_attachments(msg):
    return [p for p in msg.iter_attachments() if p.get_content_type() == "application/pdf"]


class TestPatronActionEmails:
    def _set_patron_email(self, client, email="jane@example.com"):
        client.patch("/api/patrons/1234567890", json={"email": email})

    def test_checkout_emails_patron_with_personalised_body(
        self, client, patron, sync_threads, patron_email_enabled
    ):
        self._set_patron_email(client)
        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            checkout_service.checkout_item(card="1234567890", barcode="9780451524935", title="1984")
            sent = mock_smtp.return_value.send_message.call_args_list
            assert len(sent) == 1
            msg = sent[0][0][0]
            assert msg["To"] == "jane@example.com"
            assert msg["From"] == "library@example.com"
            assert "Checkout confirmation" in msg["Subject"]
            body = _text_body(msg)
            assert "Hi Jane" in body
            assert "just checked out" in body
            assert '"1984"' in body
            assert len(_pdf_attachments(msg)) == 1

    def test_return_emails_patron_with_thank_you(
        self, client, patron, sync_threads, patron_email_enabled
    ):
        self._set_patron_email(client)
        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            checkout_service.checkout_item(card="1234567890", barcode="9780451524935", title="1984")
            mock_smtp.reset_mock()  # drop the checkout notification call
            checkout_service.return_item("9780451524935")
            sent = mock_smtp.return_value.send_message.call_args_list
            assert len(sent) == 1
            msg = sent[0][0][0]
            assert "Return confirmation" in msg["Subject"]
            body = _text_body(msg)
            assert "Hi Jane" in body
            assert "Thank you for returning" in body
            assert '"1984"' in body
            # No items remaining → no PDF attachment
            assert len(_pdf_attachments(msg)) == 0

    def test_renew_emails_patron_with_new_due_date(
        self, client, patron, sync_threads, patron_email_enabled
    ):
        self._set_patron_email(client)
        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            checkout_service.checkout_item(card="1234567890", barcode="9780451524935", title="1984")
            mock_smtp.reset_mock()  # drop the checkout notification call
            checkout_service.renew_item("9780451524935", loan_days=21)
            sent = mock_smtp.return_value.send_message.call_args_list
            assert len(sent) == 1
            msg = sent[0][0][0]
            assert "Renewal confirmation" in msg["Subject"]
            body = _text_body(msg)
            assert "Hi Jane" in body
            assert "renewal" in body.lower()
            assert "21 days" in body
            assert len(_pdf_attachments(msg)) == 1

    def test_noop_when_patron_has_no_email(
        self, client, patron, sync_threads, patron_email_enabled
    ):
        """Patron without email on file should not trigger a send."""
        # patron fixture starts with no email
        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            checkout_service.checkout_item(card="1234567890", barcode="9780451524935")
            assert not mock_smtp.return_value.send_message.called

    def test_noop_when_notify_patrons_flag_disabled(self, client, patron, sync_threads):
        """NOTIFY_PATRONS_ON_ACTION=False suppresses patron emails."""
        self._set_patron_email(client)
        with (
            patch.dict(
                client.application.config,
                {
                    "SMTP_HOST": "smtp.example.com",
                    "SMTP_USER": "library@example.com",
                    "SMTP_PASSWORD": "pwd",
                    "SMTP_FROM": "library@example.com",
                    "NOTIFY_PATRONS_ON_ACTION": False,
                    "ARCHIVE_NOTIFICATIONS_ENABLED": False,
                },
                clear=False,
            ),
            patch("smtplib.SMTP") as mock_smtp,
        ):
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            checkout_service.checkout_item(card="1234567890", barcode="9780451524935")
            assert not mock_smtp.return_value.send_message.called

    def test_smtp_failure_does_not_break_action(
        self, client, patron, sync_threads, patron_email_enabled
    ):
        """Patron email failures never bubble up to the librarian."""
        self._set_patron_email(client)
        with patch("smtplib.SMTP", side_effect=RuntimeError("smtp down")):
            loan = checkout_service.checkout_item(card="1234567890", barcode="9780451524935")
            assert loan.is_active

    def test_checkout_email_shows_library_card_number(
        self, client, patron, sync_threads, patron_email_enabled
    ):
        """Every patron-facing action email must prominently show the card."""
        self._set_patron_email(client)
        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            checkout_service.checkout_item(card="1234567890", barcode="9780451524935", title="1984")
            msg = mock_smtp.return_value.send_message.call_args_list[0][0][0]
            body = _text_body(msg)
            assert "Library card: 1234567890" in body

    def test_return_email_shows_library_card_number(
        self, client, patron, sync_threads, patron_email_enabled
    ):
        self._set_patron_email(client)
        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            checkout_service.checkout_item(card="1234567890", barcode="9780451524935")
            mock_smtp.reset_mock()
            checkout_service.return_item("9780451524935")
            msg = mock_smtp.return_value.send_message.call_args_list[0][0][0]
            body = _text_body(msg)
            assert "Library card: 1234567890" in body

    def test_renew_email_shows_library_card_number(
        self, client, patron, sync_threads, patron_email_enabled
    ):
        self._set_patron_email(client)
        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            checkout_service.checkout_item(card="1234567890", barcode="9780451524935")
            mock_smtp.reset_mock()
            checkout_service.renew_item("9780451524935")
            msg = mock_smtp.return_value.send_message.call_args_list[0][0][0]
            body = _text_body(msg)
            assert "Library card: 1234567890" in body


# ── Welcome email on new patron registration ────────────────────────────────


class TestPatronWelcomeEmail:
    def test_registration_with_email_sends_welcome(
        self, client, sync_threads, patron_email_enabled
    ):
        """New patrons with an email on file get an auto-welcome with card PDF."""
        from datetime import date

        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            checkout_service.get_or_create_patron(
                card="1234567890",
                first_name="Jane",
                last_name="Doe",
                birth_date=date(1990, 1, 15),
                email="jane@example.com",
            )
            sent = mock_smtp.return_value.send_message.call_args_list
            assert len(sent) == 1
            msg = sent[0][0][0]
            assert msg["To"] == "jane@example.com"
            assert msg["From"] == "library@example.com"
            assert "Welcome" in msg["Subject"]
            body = _text_body(msg)
            assert "Hi Jane" in body
            assert "Library card: 1234567890" in body
            # Welcome email always attaches the patron card PDF (scannable barcode)
            assert len(_pdf_attachments(msg)) == 1

    def test_registration_without_email_sends_nothing(
        self, client, sync_threads, patron_email_enabled
    ):
        from datetime import date

        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            checkout_service.get_or_create_patron(
                card="1234567890",
                first_name="Jane",
                last_name="Doe",
                birth_date=date(1990, 1, 15),
                # no email
            )
            assert not mock_smtp.return_value.send_message.called

    def test_welcome_email_disabled_by_flag(self, client, sync_threads):
        """NOTIFY_PATRONS_ON_ACTION=False suppresses the welcome too."""
        from datetime import date

        with (
            patch.dict(
                client.application.config,
                {
                    "SMTP_HOST": "smtp.example.com",
                    "SMTP_USER": "library@example.com",
                    "SMTP_PASSWORD": "pwd",
                    "SMTP_FROM": "library@example.com",
                    "NOTIFY_PATRONS_ON_ACTION": False,
                    "ARCHIVE_NOTIFICATIONS_ENABLED": False,
                },
                clear=False,
            ),
            patch("smtplib.SMTP") as mock_smtp,
        ):
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            checkout_service.get_or_create_patron(
                card="1234567890",
                first_name="Jane",
                last_name="Doe",
                birth_date=date(1990, 1, 15),
                email="jane@example.com",
            )
            assert not mock_smtp.return_value.send_message.called

    def test_existing_patron_lookup_does_not_send_welcome(
        self, client, patron, sync_threads, patron_email_enabled
    ):
        """get_or_create_patron on an existing card is a read, not a register."""
        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
            checkout_service.get_or_create_patron(card="1234567890")
            assert not mock_smtp.return_value.send_message.called
