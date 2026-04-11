"""Configuration classes — dev / prod / test."""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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

    LIBRARY_BRANCH = os.getenv("LIBRARY_BRANCH", "Fresno Central Library")
    LIBRARY_PHONE = os.getenv("LIBRARY_PHONE", "(559) 600-7323")

    # Default checkout period in weeks (matches the legacy VBA default)
    DEFAULT_CHECKOUT_WEEKS = 3
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
    name = name or os.getenv("FLASK_ENV", "development")
    return _CONFIGS.get(name, DevConfig)
