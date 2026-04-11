"""Pytest fixtures — fresh in-memory DB per test."""

from datetime import date

import pytest

from server.app import create_app
from server.app.database import db


@pytest.fixture
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

        # Clear the stats cache so it doesn't leak between tests
        from server.app.services import checkout_service

        checkout_service._stats_cache = None
        checkout_service._stats_cache_time = 0


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def patron(app):
    """Pre-seeded patron for tests that need one."""
    from server.app.services.checkout_service import get_or_create_patron

    return get_or_create_patron(
        card="1234567890",
        first_name="JANE",
        last_name="DOE",
        birth_date=date(1990, 1, 15),
    )
