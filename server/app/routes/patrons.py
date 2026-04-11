"""Patron endpoints — summary, registration, history.

Blueprinted under ``/api/patrons``.  All responses are JSON.
"""

from flask import Blueprint, jsonify, request

from ..services import checkout_service
from ..services.validators import ValidationError

bp = Blueprint("patrons", __name__, url_prefix="/api/patrons")


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
        name (str): Patron name in "LAST, FIRST" or "First Last" format.
        email (str, optional): Contact email address.

    Returns:
        201 with patron JSON on success.
        400 ``{"error": "..."}`` on validation failure (bad card, missing name, etc.).
    """
    data = request.get_json() or {}
    try:
        patron = checkout_service.get_or_create_patron(
            card=data.get("card_number", ""),
            name=data.get("name"),
            email=data.get("email"),
        )
        return jsonify(patron.to_dict()), 201
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
