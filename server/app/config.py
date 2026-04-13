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

load_dotenv()


def _project_root() -> Path:
    """Return the directory where ``data/`` and ``logs/`` should live.

    When running from source, this is the repo root — two levels above
    this file.  When running as a PyInstaller one-file bundle, ``__file__``
    points inside a temporary extraction directory that is wiped on exit,
    so we use the folder containing the ``.exe`` instead.  That folder
    persists across launches and across binary upgrades, so the SQLite
    database survives when the user replaces the executable.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = _project_root()


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
