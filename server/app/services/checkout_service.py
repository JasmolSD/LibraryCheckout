"""Checkout business logic — port of VBA Barcode() / addmaterials() subs."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from flask import current_app
from sqlalchemy import func

from ..database import db
from ..models import Book, Loan, Patron, Transaction
from .email_service import send_notification_email, send_patron_action_email
from .receipt_service import (
    ActionKind,
    build_patron_action_email,
    build_patron_card_pdf,
    build_patron_welcome_email,
    build_receipt_pdf,
)
from .validators import (
    ValidationError,
    validate_barcode,
    validate_card,
)


def _utcnow() -> datetime:
    """Return current UTC time as a naive datetime (SQLite-compatible)."""
    return datetime.now(UTC).replace(tzinfo=None)


def _fmt_local(dt: datetime | None) -> str:
    """Render a stored (naive, UTC) datetime as a local-time string.

    Used for the archival notification emails so the library staff see
    human-readable local timestamps instead of UTC.
    """
    if dt is None:
        return "—"
    # Stored values are naive UTC. Attach UTC then convert to the
    # machine's local timezone.
    local = dt.replace(tzinfo=UTC).astimezone()
    return local.strftime("%Y-%m-%d %I:%M %p %Z").strip()


def _notify_patron_of_action(action: ActionKind, patron: Patron, loan: Loan) -> None:
    """Fire a confirmation email to the patron about a checkout / renew / return.

    No-op when the patron has no email on file, SMTP isn't set, or the
    ``NOTIFY_PATRONS`` flag is disabled. Attaches a PDF receipt of the
    patron's currently-active loans (except on a return that leaves
    them with no items).
    """
    if not patron.email:
        return
    # Remaining active loans AFTER the action
    remaining = [ln for ln in patron.loans if ln.returned_at is None]
    subject, body = build_patron_action_email(action, patron, loan, remaining)

    pdf_bytes: bytes | None = None
    pdf_filename: str | None = None
    if remaining:
        try:
            pdf_bytes = build_receipt_pdf(patron, remaining)
            pdf_filename = f"receipt_{patron.card_number[-4:]}.pdf"
        except Exception as exc:  # pragma: no cover — ReportLab edge cases
            current_app.logger.warning("Receipt PDF build failed for email: %s", exc)

    send_patron_action_email(
        to=patron.email,
        subject=subject,
        body=body,
        pdf_bytes=pdf_bytes,
        pdf_filename=pdf_filename,
    )


# ── Stats cache ──────────────────────────────────────────────────────────────

_STATS_CACHE_TTL = 30  # seconds
_stats_cache: dict | None = None
_stats_cache_time: float = 0


def next_card_number() -> str:
    """Return the next sequential 14-digit library card number.

    Scans all existing card numbers numerically and returns max + 1,
    starting from ``10000000000001`` when no patrons exist yet.
    """
    base = 10_000_000_000_001
    rows = db.session.query(Patron.card_number).all()
    max_num = base - 1
    for (c,) in rows:
        try:
            n = int(c)
            if n > max_num:
                max_num = n
        except (ValueError, TypeError):
            continue
    return str(max_num + 1)


def get_or_create_patron(
    card: str,
    first_name: str | None = None,
    last_name: str | None = None,
    middle_name: str | None = None,
    birth_date: date | None = None,
    email: str | None = None,
    phone: str | None = None,
) -> Patron:
    """Look up a patron by card number, registering a new one if not found."""
    card = validate_card(card)
    patron = Patron.query.filter_by(card_number=card).first()
    if patron:
        return patron
    if not first_name or not first_name.strip():
        raise ValidationError("First name required for new patron registration")
    if not last_name or not last_name.strip():
        raise ValidationError("Last name required for new patron registration")
    if birth_date is None:
        raise ValidationError("Birth date required for new patron registration")
    patron = Patron(
        card_number=card,
        first_name=first_name.strip().upper(),
        last_name=last_name.strip().upper(),
        middle_name=middle_name.strip().upper() if middle_name and middle_name.strip() else None,
        birth_date=birth_date,
        email=email,
        phone=phone,
    )
    db.session.add(patron)
    db.session.commit()
    current_app.logger.info("Registered new patron %s", patron.masked_card)

    # Archival notification — fire-and-forget, background thread.
    # Only sent for brand-new registrations, not for get-or-create hits.
    library_name = current_app.config.get("LIBRARY_NAME", "Library")
    library_branch = current_app.config.get("LIBRARY_BRANCH", "")
    signature = f"— {library_name}" + (f" / {library_branch}" if library_branch else "")
    send_notification_email(
        subject=f"[Library Patron] New — {patron.name} ({patron.card_number})",
        body=(
            f"A new patron was registered.\n\n"
            f"Card:    {patron.card_number}\n"
            f"Name:    {patron.name}\n"
            f"DOB:     {patron.birth_date.isoformat() if patron.birth_date else '—'}\n"
            f"Email:   {patron.email or '—'}\n"
            f"Phone:   {patron.phone or '—'}\n\n"
            f"Registered: {_fmt_local(patron.created_at)}\n\n"
            f"{signature}\n"
        ),
        folder=current_app.config.get("LIBRARY_PATRONS_LABEL", "Library Patrons"),
    )

    # Welcome email to the new patron — fire-and-forget, background thread.
    # Skips silently when the patron has no email, SMTP isn't set, or the
    # NOTIFY_PATRONS flag is off.
    if patron.email:
        try:
            pdf_bytes = build_patron_card_pdf(patron)
            pdf_filename = f"library_card_{patron.card_number}.pdf"
        except Exception as exc:  # pragma: no cover — ReportLab edge cases
            current_app.logger.warning("Patron card PDF build failed for welcome: %s", exc)
            pdf_bytes = None
            pdf_filename = None
        welcome_subject, welcome_body = build_patron_welcome_email(patron)
        send_patron_action_email(
            to=patron.email,
            subject=welcome_subject,
            body=welcome_body,
            pdf_bytes=pdf_bytes,
            pdf_filename=pdf_filename,
        )

    return patron


def update_patron(
    card: str,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    middle_name: str | None = None,
    birth_date: date | None = None,
    email: str | None = None,
    phone: str | None = None,
) -> Patron:
    """Edit a patron's profile in place.

    Only non-None arguments are applied. Pass an empty string for
    ``middle_name`` / ``email`` / ``phone`` to clear those optional
    fields. Names are uppercased to match the stored format.

    Raises:
        ValidationError: If the card is invalid, the patron is not
            found, or first/last name is blanked out (they're required).
    """
    card = validate_card(card)
    patron = Patron.query.filter_by(card_number=card).first()
    if not patron:
        raise ValidationError("Patron not found")

    # Snapshot the "before" state so we can compute a diff for the
    # archival notification email once the update commits.
    before = {
        "first_name": patron.first_name,
        "last_name": patron.last_name,
        "middle_name": patron.middle_name,
        "birth_date": patron.birth_date.isoformat() if patron.birth_date else None,
        "email": patron.email,
        "phone": patron.phone,
    }

    if first_name is not None:
        stripped = first_name.strip()
        if not stripped:
            raise ValidationError("First name cannot be empty")
        patron.first_name = stripped.upper()
    if last_name is not None:
        stripped = last_name.strip()
        if not stripped:
            raise ValidationError("Last name cannot be empty")
        patron.last_name = stripped.upper()
    if middle_name is not None:
        cleaned = middle_name.strip()
        patron.middle_name = cleaned.upper() if cleaned else None
    if birth_date is not None:
        patron.birth_date = birth_date
    if email is not None:
        cleaned = email.strip()
        patron.email = cleaned or None
    if phone is not None:
        cleaned = phone.strip()
        patron.phone = cleaned or None

    after = {
        "first_name": patron.first_name,
        "last_name": patron.last_name,
        "middle_name": patron.middle_name,
        "birth_date": patron.birth_date.isoformat() if patron.birth_date else None,
        "email": patron.email,
        "phone": patron.phone,
    }
    diffs = [(k, before[k], after[k]) for k in before if before[k] != after[k]]

    db.session.commit()
    current_app.logger.info("Updated patron %s", patron.masked_card)

    # Archival notification — only when something actually changed.
    if diffs:
        library_name = current_app.config.get("LIBRARY_NAME", "Library")
        library_branch = current_app.config.get("LIBRARY_BRANCH", "")
        signature = f"— {library_name}" + (f" / {library_branch}" if library_branch else "")

        def _fmt(val):
            return "None" if val is None else f'"{val}"'

        change_lines = "\n".join(f"  {k}: {_fmt(b)} → {_fmt(a)}" for k, b, a in diffs)
        send_notification_email(
            subject=f"[Library Patron] Updated — {patron.name} ({patron.card_number})",
            body=(
                f"A patron profile was edited.\n\n"
                f"Card:    {patron.card_number}\n"
                f"Name:    {patron.name}\n\n"
                f"Changes:\n{change_lines}\n\n"
                f"Updated: {_fmt_local(_utcnow())}\n\n"
                f"{signature}\n"
            ),
            folder=current_app.config.get("LIBRARY_PATRONS_LABEL", "Library Patrons"),
        )

    return patron


def add_book_to_catalog(
    barcode: str,
    title: str | None = None,
    author: str | None = None,
    category: str = "book",
    quantity: int = 1,
) -> Book:
    """Add a new item to the catalog without checking it out.

    Args:
        quantity: Number of physical copies to add to inventory (default 1).
    """
    barcode = validate_barcode(barcode)
    if quantity < 1:
        raise ValidationError("Quantity must be at least 1")
    if Book.query.filter_by(barcode=barcode).first():
        raise ValidationError(f"Item {barcode} is already in the catalog")
    book = Book(
        barcode=barcode,
        title=title.strip() if title and title.strip() else None,
        author=author.strip() if author and author.strip() else None,
        category=category or "book",
        total_copies=quantity,
    )
    db.session.add(book)
    db.session.commit()
    current_app.logger.info("Added to catalog: %s (qty=%d)", barcode, quantity)
    return book


def update_book_quantity(barcode: str, total_copies: int) -> Book:
    """Set the total number of physical copies for an existing book.

    Raises:
        ValidationError: if the new total is less than the number of copies
            currently checked out, or if the barcode is unknown.
    """
    barcode = validate_barcode(barcode)
    if total_copies < 0:
        raise ValidationError("Quantity cannot be negative")
    book = Book.query.filter_by(barcode=barcode).first()
    if not book:
        raise ValidationError(f"Unknown item {barcode}")
    out = book.checked_out_count
    if total_copies < out:
        raise ValidationError(
            f"Cannot set quantity to {total_copies} — {out} copy/copies currently checked out"
        )
    book.total_copies = total_copies
    db.session.commit()
    current_app.logger.info("Updated quantity for %s to %d", barcode, total_copies)
    return book


def overdue_items() -> list[dict]:
    """Return all currently overdue loans with patron and book details."""
    now = _utcnow()
    rows = (
        Loan.query.filter(
            Loan.returned_at.is_(None),
            Loan.due_date < now,
        )
        .join(Patron, Loan.patron_id == Patron.id)
        .join(Book, Loan.book_id == Book.id)
        .order_by(Loan.due_date.asc())
        .all()
    )
    result = []
    for loan in rows:
        days = (now - loan.due_date).days
        result.append(
            {
                "patron_name": loan.patron.name,
                "card_number": loan.patron.card_number,
                "card_masked": loan.patron.masked_card,
                "book_title": loan.book.title or "(untitled)",
                "barcode": loan.book.barcode,
                "category": loan.book.category,
                "checked_out_at": loan.checked_out_at.isoformat(),
                "due_date": loan.due_date.isoformat(),
                "days_overdue": days,
            }
        )
    return result


def search_books(query: str, limit: int = 20) -> list[Book]:
    """Search the catalog by barcode prefix, title, or author.

    Wildcard behaviour: if ``query`` ends with ``*`` the remainder is
    treated as a strict barcode prefix and title/author matching is
    suppressed (e.g. ``456000034*`` → all books whose barcode starts
    with ``456000034``).

    Without a wildcard, the query matches against:
      * barcode (starts-with)
      * title (contains, case-insensitive via SQLite default LIKE)
      * author (contains)

    Active books are ordered ahead of archived ones, then by title.
    """
    q = query.strip()
    if not q:
        return []

    has_wildcard = q.endswith("*")
    if has_wildcard:
        prefix = q.rstrip("*")
        if not prefix:
            # Bare "*" returns everything, bounded by limit
            return Book.query.order_by(Book.is_active.desc(), Book.title.asc()).limit(limit).all()
        return (
            Book.query.filter(Book.barcode.startswith(prefix))
            .order_by(Book.is_active.desc(), Book.barcode.asc())
            .limit(limit)
            .all()
        )

    return (
        Book.query.filter(
            db.or_(
                Book.barcode.startswith(q),
                Book.title.contains(q),
                Book.author.contains(q),
            )
        )
        .order_by(Book.is_active.desc(), Book.title.asc())
        .limit(limit)
        .all()
    )


def book_details(barcode: str) -> dict:
    """Return details about a book including its current inventory and loan status.

    ``active_loans`` is aggregated by patron: a patron holding multiple
    copies of the same book appears once with ``copies_count`` and a
    ``copies`` list of the individual loan records (earliest first).
    """
    barcode = validate_barcode(barcode)
    book = Book.query.filter_by(barcode=barcode).first()
    if not book:
        raise ValidationError(f"Unknown item {barcode}")

    loans = (
        Loan.query.filter_by(book_id=book.id, returned_at=None)
        .order_by(Loan.checked_out_at.asc())
        .all()
    )

    # Group loans by patron, preserving first-seen order.
    grouped: dict[int, dict] = {}
    for loan in loans:
        bucket = grouped.get(loan.patron_id)
        if bucket is None:
            bucket = {
                "patron_name": loan.patron.name,
                "card_number": loan.patron.card_number,
                "card_masked": loan.patron.masked_card,
                "copies_count": 0,
                "copies": [],
            }
            grouped[loan.patron_id] = bucket
        bucket["copies_count"] += 1
        bucket["copies"].append(
            {
                "checked_out_at": loan.checked_out_at.isoformat(),
                "due_date": loan.due_date.isoformat() if loan.due_date else None,
            }
        )

    result = book.to_dict()
    result["checked_out"] = len(loans) > 0
    result["active_loans"] = list(grouped.values())
    return result


def get_or_create_book(barcode: str, title: str | None = None, category: str = "book") -> Book:
    """Look up an item by barcode, creating a new record if not found."""
    book = Book.query.filter_by(barcode=barcode).first()
    if book:
        if title and not book.title:
            book.title = title
        return book
    book = Book(barcode=barcode, title=title, category=category, total_copies=1)
    db.session.add(book)
    db.session.flush()
    return book


def checkout_item(
    card: str,
    barcode: str,
    loan_days: int = 14,
    category: str = "book",
    title: str | None = None,
) -> Loan:
    """Check out a single item to a patron.

    Creates a Loan record and a corresponding Transaction audit entry.
    """
    patron = Patron.query.filter_by(card_number=validate_card(card)).first()
    if not patron:
        raise ValidationError("Patron not found — register first")
    if not patron.is_active:
        raise ValidationError("Patron account is archived — reactivate before checking out")

    barcode = validate_barcode(barcode)

    book = get_or_create_book(barcode, title=title, category=category)
    if not book.is_active:
        raise ValidationError(f"Item {barcode} is archived — reactivate before checking out")

    if book.available_copies <= 0:
        raise ValidationError(
            f"No copies of item {barcode} are available " f"(all {book.total_copies} checked out)"
        )

    now = _utcnow()
    due = now + timedelta(days=loan_days)
    loan = Loan(
        patron_id=patron.id,
        book_id=book.id,
        loan_days=loan_days,
        checked_out_at=now,
        due_date=due,
    )
    db.session.add(loan)
    db.session.flush()

    txn = Transaction(loan_id=loan.id, action="checkout", created_at=now)
    db.session.add(txn)
    db.session.commit()

    current_app.logger.info(
        "Checkout: patron=%s book=%s loan_days=%d", patron.masked_card, barcode, loan_days
    )

    # Archival notification — fire-and-forget, background thread
    library_name = current_app.config.get("LIBRARY_NAME", "Library")
    library_branch = current_app.config.get("LIBRARY_BRANCH", "")
    signature = f"— {library_name}" + (f" / {library_branch}" if library_branch else "")
    title_display = f'"{book.title}"' if book.title else f"barcode {book.barcode}"
    send_notification_email(
        subject=f"[Library Receipt] {patron.name} — {title_display}",
        body=(
            f"A checkout was recorded.\n\n"
            f"Patron:  {patron.name}\n"
            f"Card:    {patron.card_number}\n"
            f"Email:   {patron.email or '—'}\n\n"
            f"Item:    {title_display}\n"
            f"Author:  {book.author or '—'}\n"
            f"Barcode: {book.barcode}\n"
            f"Category: {book.category}\n\n"
            f"Loan days: {loan_days}\n"
            f"Checked out: {_fmt_local(now)}\n"
            f"Due date:    {_fmt_local(due)}\n\n"
            f"{signature}\n"
        ),
        folder=current_app.config.get("LIBRARY_RECEIPTS_LABEL", "Library Receipts"),
    )

    # Patron-facing confirmation email (fire-and-forget)
    _notify_patron_of_action("checkout", patron, loan)

    return loan


def return_item(barcode: str, card: str | None = None) -> Loan:
    """Mark an active loan for an item as returned.

    When multiple copies of the same barcode are on loan simultaneously,
    passing ``card`` returns that specific patron's copy; otherwise the
    oldest active loan for the barcode is returned.
    """
    barcode = validate_barcode(barcode)
    book = Book.query.filter_by(barcode=barcode).first()
    if not book:
        raise ValidationError(f"Unknown item {barcode}")

    query = Loan.query.filter_by(book_id=book.id, returned_at=None)
    if card:
        patron = Patron.query.filter_by(card_number=validate_card(card)).first()
        if not patron:
            raise ValidationError("Patron not found")
        query = query.filter_by(patron_id=patron.id)
    active = query.order_by(Loan.checked_out_at.asc()).first()
    if not active:
        raise ValidationError(f"Item {barcode} is not currently checked out")

    now = _utcnow()
    active.returned_at = now

    txn = Transaction(loan_id=active.id, action="return", created_at=now)
    db.session.add(txn)
    db.session.commit()

    current_app.logger.info("Return: book=%s", barcode)

    # Patron-facing confirmation email (fire-and-forget)
    _notify_patron_of_action("return", active.patron, active)

    return active


def renew_item(barcode: str, loan_days: int = 14, card: str | None = None) -> Loan:
    """Extend the due date of an active loan from today.

    When multiple copies are on loan, passing ``card`` targets that specific
    patron's copy; otherwise the oldest active loan for the barcode is renewed.
    """
    barcode = validate_barcode(barcode)
    book = Book.query.filter_by(barcode=barcode).first()
    if not book:
        raise ValidationError(f"Unknown item {barcode}")
    query = Loan.query.filter_by(book_id=book.id, returned_at=None)
    if card:
        patron = Patron.query.filter_by(card_number=validate_card(card)).first()
        if not patron:
            raise ValidationError("Patron not found")
        query = query.filter_by(patron_id=patron.id)
    active = query.order_by(Loan.checked_out_at.asc()).first()
    if not active:
        raise ValidationError(f"Item {barcode} is not currently checked out")

    now = _utcnow()
    active.due_date = now + timedelta(days=loan_days)
    active.loan_days = loan_days

    txn = Transaction(loan_id=active.id, action="renew", created_at=now)
    db.session.add(txn)
    db.session.commit()

    current_app.logger.info("Renew: book=%s loan_days=%d", barcode, loan_days)

    # Patron-facing confirmation email (fire-and-forget)
    _notify_patron_of_action("renew", active.patron, active)

    return active


def library_stats(*, force: bool = False) -> dict:
    """Aggregate library-wide statistics for the dashboard.

    Results are cached for ``_STATS_CACHE_TTL`` seconds.  Pass
    ``force=True`` to bypass the cache (e.g. when the user clicks Refresh).
    """
    global _stats_cache, _stats_cache_time  # noqa: PLW0603

    import time

    if (
        not force
        and _stats_cache is not None
        and (time.monotonic() - _stats_cache_time) < _STATS_CACHE_TTL
    ):
        return _stats_cache

    now = _utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    total_patrons = Patron.query.count()
    # Count of unique book rows (distinct titles / barcodes, incl. archived)
    total_books = Book.query.count()
    # Count of unique book rows that are currently active (not archived)
    active_titles = Book.query.filter(Book.is_active.is_(True)).count()
    # Sum of physical copies across the whole catalog
    total_copies = db.session.query(func.coalesce(func.sum(Book.total_copies), 0)).scalar() or 0

    active_checkouts = Loan.query.filter(Loan.returned_at.is_(None)).count()

    overdue_count = Loan.query.filter(
        Loan.returned_at.is_(None),
        Loan.due_date < now,
    ).count()

    total_checkout_events = Transaction.query.filter_by(action="checkout").count()

    checkouts_today = Transaction.query.filter(
        Transaction.action == "checkout",
        Transaction.created_at >= today_start,
    ).count()

    checkouts_this_week = Transaction.query.filter(
        Transaction.action == "checkout",
        Transaction.created_at >= week_start,
    ).count()

    by_category = (
        db.session.query(Book.category, func.count(Loan.id))
        .join(Loan, Loan.book_id == Book.id)
        .filter(Loan.returned_at.is_(None))
        .group_by(Book.category)
        .order_by(func.count(Loan.id).desc())
        .all()
    )

    top_books = (
        db.session.query(Book.title, Book.barcode, func.count(Loan.id).label("cnt"))
        .join(Loan, Loan.book_id == Book.id)
        .group_by(Book.id)
        .order_by(func.count(Loan.id).desc())
        .limit(5)
        .all()
    )

    result = {
        "total_patrons": total_patrons,
        "total_books": total_books,
        "active_titles": active_titles,
        "total_copies": int(total_copies),
        "active_checkouts": active_checkouts,
        "overdue_items": overdue_count,
        "total_checkout_events": total_checkout_events,
        "checkouts_today": checkouts_today,
        "checkouts_this_week": checkouts_this_week,
        "by_category": [{"category": c, "count": n} for c, n in by_category],
        "top_books": [
            {"title": t or barcode, "barcode": barcode, "checkouts": n}
            for t, barcode, n in top_books
        ],
        "generated_at": now.isoformat(),
    }

    _stats_cache = result
    _stats_cache_time = time.monotonic()

    return result


def search_patrons(query: str) -> list[Patron]:
    """Search patrons by name or card-number prefix.

    Matches against first name, last name (case-insensitive ``contains``)
    and card number (``starts with``).  Digit-only queries still work the
    same way they always have for card lookups, plus now match partial
    card numbers; text queries match names.
    """
    raw = query.strip()
    if not raw:
        return []
    q_upper = raw.upper()
    return (
        Patron.query.filter(
            db.or_(
                Patron.last_name.contains(q_upper),
                Patron.first_name.contains(q_upper),
                Patron.card_number.startswith(raw),
            )
        )
        .limit(50)
        .all()
    )


def patron_summary(card: str) -> dict:
    """Build the dashboard summary card."""
    card = validate_card(card)
    patron = Patron.query.filter_by(card_number=card).first()
    if not patron:
        raise ValidationError("Patron not found")

    all_loans = Loan.query.filter_by(patron_id=patron.id).all()
    active = [ln for ln in all_loans if ln.is_active]
    late = [ln for ln in active if ln.is_late]

    # Build history from transactions, ordered newest first.
    # Includes loan-level events (via loan FK) and patron-level events (via patron FK).
    history = (
        Transaction.query.outerjoin(Loan, Transaction.loan_id == Loan.id)
        .filter(
            db.or_(
                Loan.patron_id == patron.id,
                Transaction.patron_id == patron.id,
            )
        )
        .order_by(Transaction.created_at.desc())
        .all()
    )

    return {
        "patron": patron.to_dict(),
        "account_age_days": (_utcnow() - patron.created_at).days,
        "total_checkouts": len(all_loans),
        "currently_out": len(active),
        "late_count": len(late),
        "active_items": [ln.to_dict() for ln in active],
        "history": [txn.to_dict() for txn in history],
    }


# ── Archive / Reactivate ────────────────────────────────────────────────────


def archive_patron(card: str) -> Patron:
    """Archive a patron account (soft-delete).

    All active loans must be returned first. Sets ``is_active = False``
    and logs an ``archive_patron`` transaction.
    """
    card = validate_card(card)
    patron = Patron.query.filter_by(card_number=card).first()
    if not patron:
        raise ValidationError("Patron not found")
    if not patron.is_active:
        raise ValidationError("Patron is already archived")

    active_loans = Loan.query.filter_by(patron_id=patron.id, returned_at=None).count()
    if active_loans:
        raise ValidationError(
            f"Cannot archive — patron has {active_loans} active loan(s). Return all items first."
        )

    patron.is_active = False
    txn = Transaction(patron_id=patron.id, action="archive_patron", created_at=_utcnow())
    db.session.add(txn)
    db.session.commit()
    current_app.logger.info("Archived patron %s", patron.masked_card)
    return patron


def reactivate_patron(card: str) -> Patron:
    """Reactivate a previously archived patron account."""
    card = validate_card(card)
    patron = Patron.query.filter_by(card_number=card).first()
    if not patron:
        raise ValidationError("Patron not found")
    if patron.is_active:
        raise ValidationError("Patron is already active")

    patron.is_active = True
    txn = Transaction(patron_id=patron.id, action="reactivate_patron", created_at=_utcnow())
    db.session.add(txn)
    db.session.commit()
    current_app.logger.info("Reactivated patron %s", patron.masked_card)
    return patron


def archive_book(barcode: str) -> Book:
    """Archive a book from the catalog (soft-delete).

    The book must not be currently checked out. Sets ``is_active = False``
    and logs an ``archive_book`` transaction.
    """
    barcode = validate_barcode(barcode)
    book = Book.query.filter_by(barcode=barcode).first()
    if not book:
        raise ValidationError(f"Unknown item {barcode}")
    if not book.is_active:
        raise ValidationError(f"Item {barcode} is already archived")

    active_loan = Loan.query.filter_by(book_id=book.id, returned_at=None).first()
    if active_loan:
        raise ValidationError(
            f"Cannot archive — item {barcode} is currently checked out. Return it first."
        )

    book.is_active = False
    txn = Transaction(book_id=book.id, action="archive_book", created_at=_utcnow())
    db.session.add(txn)
    db.session.commit()
    current_app.logger.info("Archived book %s", barcode)
    return book


def reactivate_book(barcode: str) -> Book:
    """Reactivate a previously archived book."""
    barcode = validate_barcode(barcode)
    book = Book.query.filter_by(barcode=barcode).first()
    if not book:
        raise ValidationError(f"Unknown item {barcode}")
    if book.is_active:
        raise ValidationError(f"Item {barcode} is already active")

    book.is_active = True
    txn = Transaction(book_id=book.id, action="reactivate_book", created_at=_utcnow())
    db.session.add(txn)
    db.session.commit()
    current_app.logger.info("Reactivated book %s", barcode)
    return book
