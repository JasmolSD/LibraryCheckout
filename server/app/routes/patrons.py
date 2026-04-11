"""Patron endpoints — summary, registration, history."""

from flask import Blueprint, jsonify, request
from ..services import checkout_service
from ..services.validators import ValidationError

bp = Blueprint("patrons", __name__, url_prefix="/api/patrons")


@bp.get("/<card>")
def get_patron(card):
    try:
        return jsonify(checkout_service.patron_summary(card))
    except ValidationError as e:
        return jsonify({"error": str(e)}), 404


@bp.post("/")
def create_patron():
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
