"""PDF receipt generation — replaces VBA printslip/appendlist."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Literal

from flask import current_app
from reportlab.graphics.barcode import code128
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from ..models import Loan, Patron

ActionKind = Literal["checkout", "renew", "return"]


def _greeting_first_name(patron: Patron) -> str:
    """Return the patron's first name in title-case for email greetings."""
    name = (patron.first_name or "").strip()
    return name.title() if name else "there"


def _fmt_local(dt: datetime | None) -> str:
    """Render a stored (naive, UTC) datetime as a human-friendly local string."""
    if dt is None:
        return "—"
    return dt.replace(tzinfo=UTC).astimezone().strftime("%B %d, %Y at %I:%M %p")


def _fmt_due_local(dt: datetime | None) -> str:
    """Due dates get a shorter format — just the calendar day."""
    if dt is None:
        return "—"
    return dt.replace(tzinfo=UTC).astimezone().strftime("%A, %B %d, %Y")


def _library_signature() -> str:
    """Return the ``— Library / Branch`` sign-off used in emails."""
    name = current_app.config.get("LIBRARY_NAME", "Library")
    branch = current_app.config.get("LIBRARY_BRANCH", "")
    return f"— {name}" + (f" / {branch}" if branch else "")


def build_patron_action_email(
    action: ActionKind,
    patron: Patron,
    loan: Loan,
    active_items: list[Loan],
) -> tuple[str, str]:
    """Return the (subject, plain-text body) for a patron action email.

    Covers all three librarian-driven events:

    * ``checkout`` — personalised greeting, item description, due date,
      and a count of what's currently on loan
    * ``renew`` — same layout, framed as a renewal, shows the new due date
    * ``return`` — personalised thank-you, no PDF footer when the patron
      has nothing else checked out

    Args:
        action: Which librarian action is being announced.
        patron: The :class:`Patron` the email is going to.
        loan: The specific :class:`Loan` that was just affected.
        active_items: The patron's **remaining** active loans AFTER the
            action, used for the "N item(s) still on loan" footer.
    """
    library_name = current_app.config.get("LIBRARY_NAME", "Library")
    greeting = _greeting_first_name(patron)
    item = loan.item
    title_display = f'"{item.title}"' if item and item.title else f"barcode {item.barcode}"
    author_line = f"  Author:      {item.author}\n" if item and item.author else ""
    barcode_line = f"  Barcode:     {item.barcode}\n" if item else ""
    category_line = f"  Category:    {item.category}\n" if item else ""

    count = len(active_items)
    if count == 0:
        count_footer = "You have no items on loan right now. Visit us again soon!"
    elif count == 1:
        count_footer = (
            "You currently have 1 item on loan. An updated receipt listing "
            "it is attached as a PDF."
        )
    else:
        count_footer = (
            f"You currently have {count} items on loan. An updated receipt "
            f"listing them all is attached as a PDF."
        )

    if action == "checkout":
        subject = f"{library_name} — Checkout confirmation for {title_display}"
        lead = (
            f"You just checked out {title_display} from {library_name}. "
            f"Please keep this email for your records — the attached PDF "
            f"is your receipt."
        )
        details = (
            f"Checkout details:\n"
            f"  Item:        {title_display}\n"
            f"{author_line}"
            f"{barcode_line}"
            f"{category_line}"
            f"  Loan length: {loan.loan_days} days\n"
            f"  Checked out: {_fmt_local(loan.checked_out_at)}\n"
            f"  Due date:    {_fmt_due_local(loan.due_date)}\n"
        )
    elif action == "renew":
        subject = f"{library_name} — Renewal confirmation for {title_display}"
        lead = (
            f"Your renewal of {title_display} is confirmed at {library_name}. "
            f"An updated receipt is attached as a PDF."
        )
        details = (
            f"Renewal details:\n"
            f"  Item:        {title_display}\n"
            f"{author_line}"
            f"{barcode_line}"
            f"{category_line}"
            f"  Loan length: {loan.loan_days} days (from today)\n"
            f"  New due:     {_fmt_due_local(loan.due_date)}\n"
        )
    else:  # return
        subject = f"{library_name} — Return confirmation for {title_display}"
        lead = (
            f"Thank you for returning {title_display} to {library_name}. "
            f"We hope you enjoyed it!"
        )
        details = (
            f"Return details:\n"
            f"  Item:        {title_display}\n"
            f"{author_line}"
            f"{barcode_line}"
            f"{category_line}"
            f"  Returned on: {_fmt_local(loan.returned_at)}\n"
        )

    account_block = (
        f"Account:\n" f"  Name:         {patron.name}\n" f"  Library card: {patron.card_number}\n"
    )

    body = (
        f"Hi {greeting},\n\n"
        f"{lead}\n\n"
        f"{account_block}\n"
        f"{details}\n"
        f"{count_footer}\n\n"
        f"{_library_signature()}\n"
    )
    return subject, body


def build_patron_welcome_email(patron: Patron) -> tuple[str, str]:
    """Return the (subject, plain-text body) for a patron welcome email.

    Sent automatically from ``get_or_create_patron`` when a brand-new
    patron is registered with an email on file. Always prominently
    shows the library card number so the patron has an easy digital
    record — the attached patron-card PDF has the scannable barcode.
    """
    library_name = current_app.config.get("LIBRARY_NAME", "Library")
    greeting = _greeting_first_name(patron)

    email_line = f"  Email:        {patron.email}\n" if patron.email else ""
    phone_line = f"  Phone:        {patron.phone}\n" if patron.phone else ""

    subject = f"Welcome to {library_name}!"
    body = (
        f"Hi {greeting},\n\n"
        f"Welcome to {library_name}! Your patron account has been created.\n\n"
        f"Account details:\n"
        f"  Name:         {patron.name}\n"
        f"  Library card: {patron.card_number}\n"
        f"{email_line}"
        f"{phone_line}"
        f"  Registered:   {_fmt_local(patron.created_at)}\n\n"
        f"Your patron card is attached as a PDF. It contains a scannable "
        f"barcode of your library card number — bring it (printed or on "
        f"your phone) next time you visit so we can check out items faster.\n\n"
        f"{_library_signature()}\n"
    )
    return subject, body


def build_receipt_pdf(patron: Patron, items: list[Loan]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    width, height = LETTER
    y = height - 60

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, y, current_app.config["LIBRARY_NAME"])
    y -= 20
    c.setFont("Helvetica", 11)
    c.drawCentredString(width / 2, y, "Checkout Receipt")
    y -= 16
    c.drawCentredString(width / 2, y, current_app.config["LIBRARY_BRANCH"])
    y -= 14
    c.drawCentredString(width / 2, y, datetime.now().strftime("%m/%d/%y %I:%M %p"))
    y -= 14
    c.drawCentredString(width / 2, y, current_app.config["LIBRARY_PHONE"])
    y -= 30

    c.setFont("Helvetica-Bold", 12)
    c.drawString(60, y, f"Patron: {patron.name}")
    y -= 16
    c.drawString(60, y, f"Card: {patron.masked_card}")
    y -= 24

    c.setFont("Helvetica-Bold", 11)
    c.drawString(60, y, "Barcode")
    c.drawString(260, y, "Title")
    c.drawString(420, y, "Due Date")
    y -= 6
    c.line(60, y, width - 60, y)
    y -= 14

    c.setFont("Helvetica", 10)
    for loan in items:
        if y < 80:
            c.showPage()
            y = height - 60
        c.drawString(60, y, loan.item.barcode)
        c.drawString(260, y, (loan.item.title or "—")[:25])
        c.drawString(420, y, loan.due_date.strftime("%m/%d/%y") if loan.due_date else "—")
        y -= 14

    y -= 10
    c.setFont("Helvetica-Bold", 12)
    c.drawString(60, y, f"TOTAL: {len(items)}")

    c.showPage()
    c.save()
    return buf.getvalue()


def build_patron_card_pdf(patron: Patron) -> bytes:
    """Render a printable patron information sheet.

    Handed to the patron at registration time — shows the library name,
    the full (unmasked) card number, the patron's full name, and optional
    contact details.  Uses the same ReportLab canvas style as the
    checkout receipt so both prints have a consistent look.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    width, height = LETTER
    y = height - 70

    # Header
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width / 2, y, current_app.config["LIBRARY_NAME"])
    y -= 22
    c.setFont("Helvetica", 12)
    c.drawCentredString(width / 2, y, "Patron Registration")
    y -= 16
    c.drawCentredString(width / 2, y, current_app.config["LIBRARY_BRANCH"])
    y -= 14
    c.drawCentredString(width / 2, y, datetime.now().strftime("%m/%d/%y %I:%M %p"))
    y -= 36

    # Outer card box — height accommodates card number, barcode, and contact fields
    box_x = 60
    box_w = width - 120
    box_h = 250
    box_top = y
    c.setStrokeColorRGB(0.85, 0.85, 0.92)
    c.setLineWidth(1.2)
    c.roundRect(box_x, y - box_h, box_w, box_h, 10, stroke=1, fill=0)

    y -= 30
    c.setFont("Helvetica-Bold", 11)
    c.drawString(box_x + 20, y, "LIBRARY CARD NUMBER")
    y -= 22
    c.setFont("Helvetica-Bold", 20)
    c.drawString(box_x + 20, y, patron.card_number)
    y -= 8

    # Scannable Code-128 barcode of the card number.
    barcode = code128.Code128(patron.card_number, barHeight=36, barWidth=1.3)
    barcode.drawOn(c, box_x + 20, y - 38)
    y -= 50

    c.setFont("Helvetica-Bold", 11)
    c.drawString(box_x + 20, y, "NAME")
    y -= 16
    c.setFont("Helvetica", 13)
    c.drawString(box_x + 20, y, patron.name)
    y -= 22

    if patron.email:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(box_x + 20, y, "EMAIL")
        y -= 13
        c.setFont("Helvetica", 11)
        c.drawString(box_x + 20, y, patron.email)
        y -= 18

    if patron.phone:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(box_x + 20, y, "PHONE")
        y -= 13
        c.setFont("Helvetica", 11)
        c.drawString(box_x + 20, y, patron.phone)
        y -= 18

    # Footer notes (positioned below the box regardless of field count)
    y = box_top - box_h - 20
    c.setFont("Helvetica", 10)
    c.setFillGray(0.4)
    c.drawString(
        box_x,
        y,
        (
            f"Registered: {patron.created_at.strftime('%m/%d/%y')}"
            if patron.created_at
            else "Registered: today"
        ),
    )
    y -= 14
    c.drawString(
        box_x,
        y,
        "Please keep this sheet for your records. Present your card number at checkout.",
    )

    c.showPage()
    c.save()
    return buf.getvalue()
