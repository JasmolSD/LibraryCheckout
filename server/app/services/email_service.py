"""Outgoing email helper — patron cards, checkout receipts, and
automated archival notifications.

Uses the Python standard library (``smtplib``/``imaplib`` + ``email``)
so no extra dependency is needed.  Reads SMTP and IMAP settings from
Flask config which come from environment variables — when ``SMTP_HOST``
is empty, email is considered disabled and every send is a no-op for
notifications or short-circuits with a :class:`EmailNotConfiguredError`
for user-initiated sends.

Two public functions:

* :func:`send_email_with_pdf` — synchronous, used by the user-clicked
  "Email Receipt" / "Email Card to Patron" buttons. Raises on failure
  so the UI can show a toast.
* :func:`send_notification_email` — fire-and-forget, used by the
  automatic archival hooks in ``checkout_service``. Never raises; logs
  warnings on failure. Runs on a daemon thread so request handlers
  don't pay the SMTP round-trip latency.
"""

from __future__ import annotations

import contextlib
import imaplib
import smtplib
import threading
import time
from email.message import EmailMessage

from flask import Flask, current_app


class EmailError(Exception):
    """Base class for email service errors."""


class EmailNotConfiguredError(EmailError):
    """Raised when SMTP is not configured (``SMTP_HOST`` empty)."""


def is_email_configured() -> bool:
    """Return True when SMTP_HOST is set in the current Flask app config."""
    return bool(current_app.config.get("SMTP_HOST"))


# ── Low-level primitives ─────────────────────────────────────────────────────


def _send_smtp(msg: EmailMessage, cfg: dict) -> None:
    """Hand a prepared :class:`EmailMessage` off to the configured SMTP server.

    Raises:
        EmailError: on any :class:`smtplib.SMTPException`.
    """
    host = cfg.get("SMTP_HOST") or ""
    port = int(cfg.get("SMTP_PORT") or 587)
    user = cfg.get("SMTP_USER") or ""
    password = cfg.get("SMTP_PASSWORD") or ""
    use_tls = bool(cfg.get("SMTP_USE_TLS", True))

    try:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            if use_tls:
                smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
    except smtplib.SMTPException as exc:
        raise EmailError(f"Failed to send email: {exc}") from exc


def _archive_imap(msg: EmailMessage, folder: str, cfg: dict) -> None:
    """APPEND a message to a named IMAP folder / Gmail label.

    No-op when IMAP is not configured. Never raises — archival is a
    best-effort background concern; the caller logs on failure.
    """
    host = cfg.get("IMAP_HOST") or ""
    if not host:
        return
    # Reuse SMTP credentials by default — Gmail uses the same app
    # password for SMTP submission and IMAP retrieval.
    user = cfg.get("IMAP_USER") or cfg.get("SMTP_USER") or ""
    password = cfg.get("IMAP_PASSWORD") or cfg.get("SMTP_PASSWORD") or ""
    if not user or not password:
        return
    port = int(cfg.get("IMAP_PORT") or 993)
    use_ssl = bool(cfg.get("IMAP_USE_SSL", True))

    cls = imaplib.IMAP4_SSL if use_ssl else imaplib.IMAP4
    client = cls(host, port)
    try:
        client.login(user, password)
        # Create the folder if it doesn't exist. Gmail creates the label
        # on first APPEND anyway, but being explicit makes behaviour
        # consistent across IMAP servers.
        with contextlib.suppress(imaplib.IMAP4.error):
            client.create(f'"{folder}"')
        flags = "(\\Seen)"
        date_time = imaplib.Time2Internaldate(time.time())
        client.append(f'"{folder}"', flags, date_time, msg.as_bytes())
    finally:
        with contextlib.suppress(Exception):
            client.logout()


# ── Public: synchronous send with PDF attachment ─────────────────────────────


def send_email_with_pdf(
    *,
    to: str,
    subject: str,
    body: str,
    pdf_bytes: bytes,
    pdf_filename: str,
) -> None:
    """Send a plain-text email with a single PDF attachment — synchronous.

    Raises:
        EmailNotConfiguredError: If ``SMTP_HOST`` is empty in app config.
        EmailError: For any other SMTP failure.
    """
    cfg = current_app.config
    if not cfg.get("SMTP_HOST"):
        raise EmailNotConfiguredError(
            "Email is not configured. Set SMTP_HOST (and friends) in your .env file."
        )
    if not to or "@" not in to:
        raise EmailError(f"Invalid recipient address: {to!r}")

    sender = cfg.get("SMTP_FROM") or cfg.get("SMTP_USER") or "noreply@library.local"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=pdf_filename,
    )

    _send_smtp(msg, dict(cfg))


# ── Public: fire-and-forget archival notifications ──────────────────────────


def send_notification_email(
    *,
    subject: str,
    body: str,
    folder: str | None = None,
) -> None:
    """Mail the library account a plain-text notification of a library event.

    Used by the automatic archival hooks in ``checkout_service`` whenever
    an item is checked out or a patron account is created / edited. The
    message is sent **from the library account to itself**, with an
    optional IMAP APPEND to a named Gmail label so the notifications
    are easy to locate later.

    This function is **fire-and-forget**:
      * runs on a daemon thread so the request handler is not blocked,
      * silently does nothing when SMTP is not configured OR when
        ``ARCHIVE_NOTIFICATIONS_ENABLED`` is False (the master on/off
        switch, settable via the ``ARCHIVE_NOTIFICATIONS`` env var),
      * logs warnings on any failure instead of raising.
    """
    if not is_email_configured():
        return
    if not current_app.config.get("ARCHIVE_NOTIFICATIONS_ENABLED", True):
        return

    app = current_app._get_current_object()  # type: ignore[attr-defined]
    cfg_snapshot = dict(app.config)
    sender = cfg_snapshot.get("SMTP_FROM") or cfg_snapshot.get("SMTP_USER") or ""
    if not sender:
        app.logger.warning("send_notification_email: no SMTP_FROM/SMTP_USER; skipping")
        return

    def _worker(app: Flask = app, cfg: dict = cfg_snapshot) -> None:
        with app.app_context():
            try:
                msg = EmailMessage()
                msg["Subject"] = subject
                msg["From"] = sender
                msg["To"] = sender
                msg.set_content(body)
                _send_smtp(msg, cfg)
                if folder:
                    try:
                        _archive_imap(msg, folder, cfg)
                    except Exception as exc:
                        app.logger.warning(
                            "Notification email archived via SMTP but IMAP "
                            "APPEND to %r failed: %s",
                            folder,
                            exc,
                        )
            except Exception as exc:
                app.logger.warning("Notification email failed: %s", exc)

    threading.Thread(target=_worker, daemon=True).start()


# ── Public: fire-and-forget patron action emails ────────────────────────────


def send_patron_action_email(
    *,
    to: str,
    subject: str,
    body: str,
    pdf_bytes: bytes | None = None,
    pdf_filename: str | None = None,
) -> None:
    """Fire-and-forget email to a patron about a checkout/renew/return.

    Mirrors :func:`send_notification_email` but:
      * sends from the library account **to the patron**,
      * optionally attaches a PDF receipt,
      * respects ``NOTIFY_PATRONS_ON_ACTION`` instead of
        ``ARCHIVE_NOTIFICATIONS_ENABLED``,
      * silently does nothing when SMTP is not configured or when the
        patron has no email on file.
    """
    if not is_email_configured():
        return
    if not current_app.config.get("NOTIFY_PATRONS_ON_ACTION", True):
        return
    if not to or "@" not in to:
        return

    app = current_app._get_current_object()  # type: ignore[attr-defined]
    cfg_snapshot = dict(app.config)
    sender = cfg_snapshot.get("SMTP_FROM") or cfg_snapshot.get("SMTP_USER") or ""
    if not sender:
        app.logger.warning("send_patron_action_email: no SMTP_FROM/SMTP_USER; skipping")
        return

    def _worker(app: Flask = app, cfg: dict = cfg_snapshot) -> None:
        with app.app_context():
            try:
                msg = EmailMessage()
                msg["Subject"] = subject
                msg["From"] = sender
                msg["To"] = to
                msg.set_content(body)
                if pdf_bytes and pdf_filename:
                    msg.add_attachment(
                        pdf_bytes,
                        maintype="application",
                        subtype="pdf",
                        filename=pdf_filename,
                    )
                _send_smtp(msg, cfg)
            except Exception as exc:
                app.logger.warning("Patron action email failed: %s", exc)

    threading.Thread(target=_worker, daemon=True).start()
