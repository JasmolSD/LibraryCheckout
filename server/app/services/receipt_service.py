"""PDF receipt generation — replaces VBA printslip/appendlist."""

from __future__ import annotations

import io
from datetime import datetime

from flask import current_app
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from ..models import Loan, Patron


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
        c.drawString(60, y, loan.book.barcode)
        c.drawString(260, y, (loan.book.title or "—")[:25])
        c.drawString(420, y, loan.due_date.strftime("%m/%d/%y") if loan.due_date else "—")
        y -= 14

    y -= 10
    c.setFont("Helvetica-Bold", 12)
    c.drawString(60, y, f"TOTAL: {len(items)}")

    c.showPage()
    c.save()
    return buf.getvalue()
