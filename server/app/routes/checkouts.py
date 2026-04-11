"""Checkout / return / renew endpoints."""

from flask import Blueprint, jsonify, request
from ..services import checkout_service
from ..services.validators import ValidationError

bp = Blueprint("checkouts", __name__, url_prefix="/api/checkouts")


@bp.post("/")
def checkout():
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
    data = request.get_json() or {}
    try:
        return jsonify(checkout_service.return_item(data.get("barcode", "")).to_dict())
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400


@bp.post("/renew")
def renew_item():
    data = request.get_json() or {}
    try:
        co = checkout_service.renew_item(data.get("barcode", ""), int(data.get("weeks", 3)))
        return jsonify(co.to_dict())
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
