"""Patron endpoints — summary, registration, search, history.

Blueprinted under ``/api/patrons``.  All responses are JSON.

Route ordering is important: ``/search`` must be registered before ``/<card>``
to prevent the literal segment being captured as a card number variable.
"""

from datetime import date

from flask import Blueprint, jsonify, request

from ..services import checkout_service
from ..services.validators import ValidationError

bp = Blueprint("patrons", __name__, url_prefix="/api/patrons")


@bp.get("/search")
def search_patrons():
    """Search patrons by first or last name.

    Query parameters:
        q (str): Search query matched case-insensitively against first and last name.

    Returns:
        200 with a list of matching patron objects (up to 50).
        400 ``{"error": "..."}`` if the query parameter is missing.
    """
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Query parameter 'q' is required"}), 400
    patrons = checkout_service.search_patrons(q)
    return jsonify([p.to_dict() for p in patrons])


@bp.get("/<card>")
def get_patron(card):
    """Return a patron summary including active items and full history.

    Args:
        card: Library card number from the URL path.

    Returns:
        200 with patron summary JSON on success.
        404 ``{"error": "..."}`` if the patron does not exist.
    """
    try:
        return jsonify(checkout_service.patron_summary(card))
    except ValidationError as e:
        return jsonify({"error": str(e)}), 404


@bp.post("/")
def create_patron():
    """Register a new patron, or return the existing record if the card already exists.

    Request body (JSON):
        card_number (str): 10- or 14-digit library card number.
        first_name (str): Patron's first name (required for new patrons).
        last_name (str): Patron's last name (required for new patrons).
        middle_name (str, optional): Patron's middle name.
        birth_date (str): ISO 8601 date string ``"YYYY-MM-DD"`` (required for new patrons).
        email (str, optional): Contact email address.
        phone (str, optional): Contact phone number.

    Returns:
        201 with patron JSON on success.
        400 ``{"error": "..."}`` on validation failure (bad card, missing required
        fields, invalid date format, etc.).
    """
    data = request.get_json() or {}

    birth_date: date | None = None
    raw_birth = data.get("birth_date")
    if raw_birth:
        try:
            birth_date = date.fromisoformat(str(raw_birth))
        except ValueError:
            return jsonify({"error": "birth_date must be in YYYY-MM-DD format"}), 400

    try:
        patron = checkout_service.get_or_create_patron(
            card=data.get("card_number", ""),
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            middle_name=data.get("middle_name"),
            birth_date=birth_date,
            email=data.get("email"),
            phone=data.get("phone"),
        )
        return jsonify(patron.to_dict()), 201
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
