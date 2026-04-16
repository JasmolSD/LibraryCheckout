"""Patron endpoints — summary, registration, search, history.

Blueprinted under ``/api/patrons``.  All responses are JSON.

Route ordering is important: ``/search`` must be registered before ``/<card>``
to prevent the literal segment being captured as a card number variable.
"""

from datetime import date

from flask import Blueprint, Response, current_app, jsonify, request

from ..models import Patron
from ..services import checkout_service
from ..services.email_service import (
    EmailError,
    EmailNotConfiguredError,
    is_email_configured,
    send_email_with_pdf,
)
from ..services.receipt_service import build_patron_card_pdf
from ..services.validators import ValidationError, validate_card

bp = Blueprint("patrons", __name__, url_prefix="/api/patrons")


@bp.get("/next-card")
def next_card():
    """Return the next auto-generated 14-digit library card number.

    Returns:
        200 with ``{"card_number": "<14-digit string>"}``
        500 with ``{"error": "..."}`` if the database is unreachable.
    """
    try:
        return jsonify({"card_number": checkout_service.next_card_number()})
    except Exception as e:
        return jsonify({"error": f"Could not generate card number: {e}"}), 500


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


@bp.patch("/<card>")
def update_patron(card):
    """Update an existing patron's profile.

    Request body (JSON): any subset of the editable fields —
    ``first_name``, ``last_name``, ``middle_name``, ``birth_date``
    (ISO 8601), ``email``, ``phone``. Omitted fields are left unchanged.
    Pass an empty string to clear an optional field.

    Returns:
        200 with updated patron JSON on success.
        400 ``{"error": "..."}`` on validation failure (bad date, blank
            required name, bad card number).
        404 if the patron is not found.
    """
    data = request.get_json() or {}
    kwargs: dict = {}

    for key in ("first_name", "last_name", "middle_name", "email", "phone"):
        if key in data:
            kwargs[key] = data[key] if data[key] is not None else ""

    if "birth_date" in data and data["birth_date"]:
        try:
            kwargs["birth_date"] = date.fromisoformat(str(data["birth_date"]))
        except ValueError:
            return jsonify({"error": "birth_date must be in YYYY-MM-DD format"}), 400

    try:
        patron = checkout_service.update_patron(card, **kwargs)
        return jsonify(patron.to_dict())
    except ValidationError as e:
        status = 404 if "not found" in str(e).lower() else 400
        return jsonify({"error": str(e)}), status


@bp.get("/<card>/card-pdf")
def patron_card_pdf(card):
    """Generate a printable patron card / info sheet as a PDF.

    Returns:
        200 ``application/pdf`` on success.
        400 if the card number is invalid.
        404 if no patron has the given card number.
    """
    try:
        card = validate_card(card)
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400

    patron = Patron.query.filter_by(card_number=card).first()
    if not patron:
        return jsonify({"error": "Patron not found"}), 404

    try:
        pdf_bytes = build_patron_card_pdf(patron)
    except Exception as exc:  # pragma: no cover — ReportLab edge cases
        current_app.logger.error("Patron card PDF generation failed: %s", exc)
        return jsonify({"error": "Failed to generate patron card"}), 500

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'inline; filename="patron_card_{card[-4:]}.pdf"'},
    )


@bp.post("/<card>/card-email")
def email_patron_card(card):
    """Email the patron their library card as a PDF attachment.

    The PDF contains a scannable Code-128 barcode of the card number,
    along with the patron's name and contact details.

    Returns:
        200 ``{"sent": true, "to": "..."}`` on success.
        400 if the card is invalid or the patron has no email address.
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

    try:
        pdf_bytes = build_patron_card_pdf(patron)
        library_name = current_app.config["LIBRARY_NAME"]
        send_email_with_pdf(
            to=patron.email,
            subject=f"Your {library_name} library card",
            body=(
                f"Hello {patron.first_name.title()},\n\n"
                f"Welcome to {library_name}!  Your library card is attached "
                f"as a PDF with a scannable barcode.\n\n"
                f"Your card number is: {patron.card_number}\n\n"
                f"Please keep this for your records and present it on "
                f"future visits.\n\n"
                f"— {library_name}"
            ),
            pdf_bytes=pdf_bytes,
            pdf_filename=f"library_card_{patron.card_number}.pdf",
        )
    except EmailNotConfiguredError as exc:
        return jsonify({"error": str(exc)}), 503
    except EmailError as exc:
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:  # pragma: no cover — ReportLab edge cases
        current_app.logger.error("Patron card email failed: %s", exc)
        return jsonify({"error": "Failed to send email"}), 500

    return jsonify({"sent": True, "to": patron.email})


@bp.post("/<card>/archive")
def archive_patron(card):
    """Archive a patron account (soft-delete).

    The patron must have no active loans. Sets the account to inactive
    and logs an ``archive_patron`` transaction.

    Returns:
        200 with patron JSON on success.
        400 ``{"error": "..."}`` if the patron has active loans or is already archived.
    """
    try:
        patron = checkout_service.archive_patron(card)
        return jsonify(patron.to_dict())
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400


@bp.post("/<card>/reactivate")
def reactivate_patron(card):
    """Reactivate a previously archived patron account.

    Returns:
        200 with patron JSON on success.
        400 ``{"error": "..."}`` if the patron is already active.
    """
    try:
        patron = checkout_service.reactivate_patron(card)
        return jsonify(patron.to_dict())
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
