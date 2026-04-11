"""Pytest fixtures — fresh in-memory DB per test."""

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


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def patron(app):
    """Pre-seeded patron for tests that need one."""
    from server.app.services.checkout_service import get_or_create_patron

    return get_or_create_patron(card="1234567890", name="DOE, JANE")
