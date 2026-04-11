"""Checkout / return / renew endpoints.

Blueprinted under ``/api/checkouts``.  All requests and responses are JSON.
"""

from flask import Blueprint, jsonify, request

from ..services import checkout_service
from ..services.validators import ValidationError

bp = Blueprint("checkouts", __name__, url_prefix="/api/checkouts")


@bp.post("/")
def checkout():
    """Check out a single item to a patron.

    Request body (JSON):
        card_number (str): Patron's library card number.
        barcode (str): Item barcode, optionally prefixed with "1W", "2W", or "3W"
            to override the default 3-week loan period.
        category (str, optional): Item category — one of book / dvd / audiobook /
            magazine / ebook / other.  Defaults to "book".
        title (str, optional): Human-readable item title stored on first encounter.

    Returns:
        201 with the new :class:`Checkout` record as JSON on success.
        400 ``{"error": "..."}`` on validation failure (patron not found, duplicate
        active checkout, invalid barcode, etc.).
    """
    data = request.get_json() or {}
    try:
        co = checkout_service.checkout_item(
            card=data.get("card_number", ""),
            item_input=data.get("barcode", ""),
            category=data.get("category", "book"),
            title=data.get("title"),
        )
        return jsonify(co.to_dict()), 201
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400


@bp.post("/return")
def return_item():
    """Mark a currently-checked-out item as returned.

    Request body (JSON):
        barcode (str): Item barcode (prefix stripped automatically).

    Returns:
        200 with the return :class:`Checkout` audit record as JSON on success.
        400 ``{"error": "..."}`` if the item is not currently checked out or the
        barcode is invalid.
    """
    data = request.get_json() or {}
    try:
        return jsonify(checkout_service.return_item(data.get("barcode", "")).to_dict())
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400


@bp.post("/renew")
def renew_item():
    """Extend the due date of a currently-checked-out item from today.

    Request body (JSON):
        barcode (str): Item barcode (prefix stripped automatically).
        weeks (int, optional): Number of weeks to add from today.  Defaults to 3.

    Returns:
        200 with the updated :class:`Checkout` record as JSON on success.
        400 ``{"error": "..."}`` if the item is not currently checked out or the
        barcode is invalid.
    """
    data = request.get_json() or {}
    try:
        weeks = int(data.get("weeks", 3))
    except (ValueError, TypeError):
        return jsonify({"error": "weeks must be an integer"}), 400
    try:
        co = checkout_service.renew_item(data.get("barcode", ""), weeks)
        return jsonify(co.to_dict())
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
