"""Receipt generation endpoint — returns a PDF.

Blueprinted under ``/api/receipts``.
"""

from flask import Blueprint, Response, jsonify

from ..models import Patron
from ..services.receipt_service import build_receipt_pdf
from ..services.validators import ValidationError, validate_card

bp = Blueprint("receipts", __name__, url_prefix="/api/receipts")


@bp.get("/<card>")
def receipt_for_active(card):
    """Generate a PDF receipt of the patron's currently-active checkouts.

    Args:
        card: Library card number from the URL path.

    Returns:
        200 ``application/pdf`` response containing the receipt on success.
        400 ``{"error": "..."}`` if the card is invalid or there are no active checkouts.
        404 ``{"error": "Patron not found"}`` if the card is unrecognised.
    """
    try:
        card = validate_card(card)
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400

    patron = Patron.query.filter_by(card_number=card).first()
    if not patron:
        return jsonify({"error": "Patron not found"}), 404

    active = [c for c in patron.checkouts.filter_by(action="checkout").all() if c.is_active]
    if not active:
        return jsonify({"error": "No active checkouts to print"}), 400

    pdf_bytes = build_receipt_pdf(patron, active)
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'inline; filename="receipt_{card[-4:]}.pdf"'},
    )
