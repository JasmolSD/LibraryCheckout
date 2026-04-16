"""Configuration classes — dev / prod / test.

Provides three concrete config classes (``DevConfig``, ``ProdConfig``,
``TestConfig``) that inherit shared settings from ``BaseConfig``.
Values can be overridden at runtime via environment variables or a ``.env``
file (loaded automatically by python-dotenv).

Usage::

    from server.app.config import get_config
    app.config.from_object(get_config("testing"))
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _project_root() -> Path:
    """Return the directory where ``data/``, ``logs/`` and ``.env`` live.

    When running from source, this is the repo root — two levels above
    this file.  When running as a PyInstaller one-file bundle, ``__file__``
    points inside a temporary extraction directory that is wiped on exit,
    so we use the folder containing the ``.exe`` instead.  That folder
    persists across launches and across binary upgrades, so the SQLite
    database and ``.env`` configuration both survive when the user
    replaces the executable.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = _project_root()

# Load .env from next to the executable (or the repo root when running
# from source).  Without the explicit path, python-dotenv only searches
# the current working directory, which is unreliable for a packaged
# desktop app launched via a Start-menu shortcut or double-click.
load_dotenv(PROJECT_ROOT / ".env")


class BaseConfig:
    ENV = "base"
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    DATA_DIR = str(PROJECT_ROOT / "data")
    LOG_DIR = os.getenv("LOG_DIR", str(PROJECT_ROOT / "logs"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{PROJECT_ROOT / 'data' / 'library.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    LIBRARY_NAME = os.getenv("LIBRARY_NAME", "Library")
    LIBRARY_BRANCH = os.getenv("LIBRARY_BRANCH", "Main Branch")
    LIBRARY_PHONE = os.getenv("LIBRARY_PHONE", "")
    LIBRARY_EMAIL = os.getenv("LIBRARY_EMAIL", "")
    LIBRARY_ADDRESS = os.getenv("LIBRARY_ADDRESS", "")
    LIBRARY_HOURS = os.getenv("LIBRARY_HOURS", "")
    APP_TITLE = os.getenv("APP_TITLE", "Library Checkout")

    # SMTP — leave SMTP_HOST empty to disable all outgoing email features.
    # When set, the app can email patron cards and checkout receipts and
    # also mail itself an archival copy of checkouts / patron edits.
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "")
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes", "on")

    # IMAP — optional. When set, archival notification emails are also
    # APPENDed to a named Gmail label / IMAP folder ("Library Receipts"
    # or "Library Patrons") so they're easy to find. Without IMAP, the
    # notifications still go out via SMTP and land in the Gmail Inbox
    # and Sent Mail naturally; only the auto-labelling is missing.
    IMAP_HOST = os.getenv("IMAP_HOST", "")
    IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
    IMAP_USER = os.getenv("IMAP_USER", "")  # falls back to SMTP_USER
    IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "")  # falls back to SMTP_PASSWORD
    IMAP_USE_SSL = os.getenv("IMAP_USE_SSL", "true").lower() in ("1", "true", "yes", "on")

    # Labels the archival notifications get filed under via IMAP APPEND
    LIBRARY_RECEIPTS_LABEL = os.getenv("LIBRARY_RECEIPTS_LABEL", "Library Receipts")
    LIBRARY_PATRONS_LABEL = os.getenv("LIBRARY_PATRONS_LABEL", "Library Patrons")

    # Master on/off switch for the automatic archival notifications.
    # When False, checkouts and patron edits still work normally but no
    # self-addressed email is sent. Default True — honours SMTP setup.
    ARCHIVE_NOTIFICATIONS_ENABLED = os.getenv("ARCHIVE_NOTIFICATIONS", "true").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    # Master on/off switch for outgoing confirmation emails TO patrons
    # whenever a librarian performs a checkout, renewal, or return.
    # Only fires when the patron has an email on file AND SMTP is set.
    NOTIFY_PATRONS_ON_ACTION = os.getenv("NOTIFY_PATRONS", "true").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    # GitHub auto-update check — compares the baked-in VERSION against
    # the latest release tag on the configured repo and surfaces a
    # banner in the UI when a newer version is available.
    GITHUB_REPO = os.getenv("GITHUB_REPO", "JasmolSD/LibraryCheckout")
    # Optional: fine-grained personal access token with contents:read
    # on the target repo, only needed if the repo is private.
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
    # Disable the update check entirely (e.g. for dev builds or
    # air-gapped installs that shouldn't call home).
    UPDATE_CHECK_ENABLED = os.getenv("UPDATE_CHECK_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    # Default checkout period in weeks
    DEFAULT_CHECKOUT_WEEKS = 2
    VALID_BARCODE_LENGTHS = (10, 14)
    MAX_ITEMS_PER_CHECKOUT = 50


class DevConfig(BaseConfig):
    ENV = "development"
    DEBUG = True


class ProdConfig(BaseConfig):
    ENV = "production"
    DEBUG = False


class TestConfig(BaseConfig):
    ENV = "testing"
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    LOG_LEVEL = "WARNING"
    # Tests run in isolation from the developer's .env so behaviour is
    # deterministic regardless of whether SMTP / IMAP are configured locally.
    SMTP_HOST = ""
    SMTP_PORT = 587
    SMTP_USER = ""
    SMTP_PASSWORD = ""
    SMTP_FROM = ""
    SMTP_USE_TLS = False
    IMAP_HOST = ""
    IMAP_PORT = 993
    IMAP_USER = ""
    IMAP_PASSWORD = ""
    IMAP_USE_SSL = False
    ARCHIVE_NOTIFICATIONS_ENABLED = False
    NOTIFY_PATRONS_ON_ACTION = False
    UPDATE_CHECK_ENABLED = False


_CONFIGS = {
    "development": DevConfig,
    "production": ProdConfig,
    "testing": TestConfig,
}


def get_config(name: str | None = None) -> type[BaseConfig]:
    """Return the config class for the given environment name.

    Args:
        name: ``"development"``, ``"production"``, or ``"testing"``.
            Falls back to the ``FLASK_ENV`` environment variable, then
            to ``"development"`` if neither is set.

    Returns:
        A :class:`BaseConfig` subclass (not an instance).
    """
    name = name or os.getenv("FLASK_ENV", "development")
    return _CONFIGS.get(name, DevConfig)
