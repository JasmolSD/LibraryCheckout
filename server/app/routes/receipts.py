"""Receipt generation endpoint — returns a PDF.

Blueprinted under ``/api/receipts``.
"""

from flask import Blueprint, Response, current_app, jsonify

from ..models import Loan, Patron
from ..services.email_service import (
    EmailError,
    EmailNotConfiguredError,
    is_email_configured,
    send_email_with_pdf,
)
from ..services.receipt_service import build_patron_action_email, build_receipt_pdf
from ..services.validators import ValidationError, validate_card

bp = Blueprint("receipts", __name__, url_prefix="/api/receipts")


@bp.get("/<card>")
def receipt_for_active(card):
    """Generate a PDF receipt of the patron's currently-active loans.

    Args:
        card: Library card number from the URL path.

    Returns:
        200 ``application/pdf`` response containing the receipt on success.
        400 ``{"error": "..."}`` if the card is invalid or there are no active loans.
        404 ``{"error": "Patron not found"}`` if the card is unrecognised.
    """
    try:
        card = validate_card(card)
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400

    patron = Patron.query.filter_by(card_number=card).first()
    if not patron:
        return jsonify({"error": "Patron not found"}), 404

    active = [ln for ln in Loan.query.filter_by(patron_id=patron.id).all() if ln.is_active]
    if not active:
        return jsonify({"error": "No active checkouts to print"}), 400

    try:
        pdf_bytes = build_receipt_pdf(patron, active)
    except Exception as exc:
        current_app.logger.error("PDF generation failed: %s", exc)
        return jsonify({"error": "Failed to generate receipt"}), 500

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'inline; filename="receipt_{card[-4:]}.pdf"'},
    )


@bp.post("/<card>/email")
def email_receipt(card):
    """Email the active-checkouts receipt to the patron's address on file.

    Returns:
        200 ``{"sent": true, "to": "..."}`` on success.
        400 if the card is invalid, the patron has no email, or there
            are no active checkouts to send.
        404 if no patron has the given card number.
        503 if SMTP is not configured on the server.
    """
    try:
        card = validate_card(card)
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400

    patron = Patron.query.filter_by(card_number=card).first()
    if not patron:
        return jsonify({"error": "Patron not found"}), 404
    if not patron.email:
        return jsonify({"error": "Patron has no email address on file"}), 400
    if not is_email_configured():
        return jsonify({"error": "Email is not configured on this server"}), 503

    active = [ln for ln in Loan.query.filter_by(patron_id=patron.id).all() if ln.is_active]
    if not active:
        return jsonify({"error": "No active checkouts to email"}), 400

    try:
        pdf_bytes = build_receipt_pdf(patron, active)
        # Use the most recently checked-out loan as the focal "action" item
        # — this is a manual resend, so "checkout" is the most natural framing.
        focal = max(active, key=lambda ln: ln.checked_out_at)
        subject, body = build_patron_action_email("checkout", patron, focal, active)
        send_email_with_pdf(
            to=patron.email,
            subject=subject,
            body=body,
            pdf_bytes=pdf_bytes,
            pdf_filename=f"receipt_{card[-4:]}.pdf",
        )
    except EmailNotConfiguredError as exc:
        return jsonify({"error": str(exc)}), 503
    except EmailError as exc:
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:  # pragma: no cover
        current_app.logger.error("Receipt email failed: %s", exc)
        return jsonify({"error": "Failed to send receipt email"}), 500

    return jsonify({"sent": True, "to": patron.email, "count": len(active)})
