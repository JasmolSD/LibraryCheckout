"""Book catalog endpoints — add items and ISBN metadata lookup.

Blueprinted under ``/api/books``.  All responses are JSON.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from flask import Blueprint, jsonify, request

from ..models import CategoryType
from ..services import checkout_service
from ..services.validators import ValidationError

bp = Blueprint("books", __name__, url_prefix="/api/books")

_CATEGORY_KEYWORDS: dict[CategoryType, list[str]] = {
    CategoryType.DVD: ["dvd", "video", "film", "movie", "motion picture"],
    CategoryType.AUDIOBOOK: ["audio", "spoken word", "sound recording"],
    CategoryType.MAGAZINE: ["magazine", "periodical", "journal", "serial"],
    CategoryType.EBOOK: ["electronic", "ebook", "e-book", "digital"],
}


def _map_category(raw_categories: list[str]) -> str:
    """Best-effort mapping from Google Books categories to our simplified set."""
    combined = " ".join(raw_categories).lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            return category
    return CategoryType.BOOK


@bp.get("/lookup")
def lookup_isbn():
    """Look up book metadata from Google Books by ISBN.

    Query parameters:
        isbn (str): ISBN-10 or ISBN-13 (digits only).

    Returns:
        200 with ``{"found": true, "title": "...", "author": "...", ...}``
        or ``{"found": false}`` when the ISBN has no match.
        400 if the ``isbn`` parameter is missing or non-numeric.
    """
    isbn = request.args.get("isbn", "").strip()
    if not isbn:
        return jsonify({"error": "isbn parameter required"}), 400
    if not isbn.isdigit():
        return jsonify({"error": "isbn must be numeric"}), 400

    url = (
        f"https://www.googleapis.com/books/v1/volumes"
        f"?q=isbn:{isbn}&maxResults=1&fields=items(volumeInfo)"
    )
    try:
        with urllib.request.urlopen(url, timeout=6) as resp:
            raw = json.loads(resp.read())
    except (urllib.error.URLError, OSError):
        return jsonify({"found": False, "error": "metadata service unavailable"}), 200
    except Exception:
        return jsonify({"found": False}), 200

    items = raw.get("items", [])
    if not items:
        return jsonify({"found": False}), 200

    info = items[0].get("volumeInfo", {})
    return jsonify(
        {
            "found": True,
            "title": info.get("title", ""),
            "subtitle": info.get("subtitle", ""),
            "author": ", ".join(info.get("authors", [])),
            "category": _map_category(info.get("categories", [])),
            "published_date": info.get("publishedDate", ""),
            "description": (info.get("description") or "")[:300],
        }
    )


@bp.get("/search")
def search_books():
    """Search the catalog by barcode prefix, title, or author.

    Query parameters:
        q (str): Search query.  A trailing ``*`` forces a strict
            barcode-prefix match (e.g. ``456000034*``).
        limit (int, optional): Maximum results (default 20, max 100).

    Returns:
        200 with ``[{barcode, title, author, ...}, ...]`` on success.
        400 if ``q`` is missing.
    """
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Query parameter 'q' is required"}), 400
    try:
        limit = min(100, max(1, int(request.args.get("limit", 20))))
    except (ValueError, TypeError):
        limit = 20
    books = checkout_service.search_books(q, limit=limit)
    return jsonify([b.to_dict() for b in books])


@bp.get("/<barcode>")
def get_book(barcode):
    """Look up a book by barcode and return its details including loan status.

    Returns:
        200 with book details JSON on success.
        400 ``{"error": "..."}`` if the barcode is invalid or unknown.
    """
    try:
        return jsonify(checkout_service.book_details(barcode))
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400


@bp.post("/")
def add_book():
    """Add a new item to the library catalog.

    Request body (JSON):
        barcode (str): ISBN-10, ISBN-13, or 14-digit library barcode.
        title (str, optional): Item title.
        author (str, optional): Author name(s).
        category (str, optional): One of book / dvd / audiobook / magazine /
            ebook / other.  Defaults to ``"book"``.
        quantity (int, optional): Number of physical copies to add (default 1).

    Returns:
        201 with the new book JSON on success.
        400 ``{"error": "..."}`` on validation failure or duplicate barcode.
    """
    data = request.get_json() or {}
    try:
        quantity = int(data.get("quantity", 1))
    except (ValueError, TypeError):
        return jsonify({"error": "quantity must be an integer"}), 400
    try:
        book = checkout_service.add_book_to_catalog(
            barcode=data.get("barcode", ""),
            title=data.get("title"),
            author=data.get("author"),
            category=data.get("category", CategoryType.BOOK),
            quantity=quantity,
        )
        return jsonify(book.to_dict()), 201
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400


@bp.patch("/<barcode>")
def edit_book(barcode):
    """Update editable metadata (barcode, title, author, category) for a catalog item.

    Request body (JSON):
        new_barcode (str, optional): Replacement barcode — must be unique and valid.
        title (str, optional): New title.
        author (str, optional): New author.
        category (str, optional): One of book / dvd / audiobook / magazine / ebook / other.

    Returns:
        200 with updated book JSON on success.
        400 ``{"error": "..."}`` on validation failure.
    """
    data = request.get_json() or {}
    try:
        book = checkout_service.edit_book(
            barcode=barcode,
            new_barcode=data.get("new_barcode"),
            title=data.get("title"),
            author=data.get("author"),
            category=data.get("category"),
        )
        return jsonify(book.to_dict())
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400


@bp.post("/<barcode>/quantity")
def update_quantity(barcode):
    """Update the total number of physical copies for an existing book.

    Request body (JSON):
        total_copies (int): New total number of copies. Cannot be less than
            the number of copies currently checked out.

    Returns:
        200 with book JSON on success.
        400 ``{"error": "..."}`` on validation failure.
    """
    data = request.get_json() or {}
    raw = data.get("total_copies")
    if raw is None:
        return jsonify({"error": "total_copies is required"}), 400
    try:
        total_copies = int(raw)
    except (ValueError, TypeError):
        return jsonify({"error": "total_copies must be an integer"}), 400
    try:
        book = checkout_service.update_book_quantity(barcode, total_copies)
        return jsonify(book.to_dict())
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400


@bp.post("/<barcode>/archive")
def archive_book(barcode):
    """Archive a book from the catalog (soft-delete).

    The book must not be currently checked out. Sets it to inactive
    and logs an ``archive_book`` transaction.

    Returns:
        200 with book JSON on success.
        400 ``{"error": "..."}`` if the book is checked out or already archived.
    """
    try:
        book = checkout_service.archive_book(barcode)
        return jsonify(book.to_dict())
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400


@bp.post("/<barcode>/reactivate")
def reactivate_book(barcode):
    """Reactivate a previously archived book.

    Returns:
        200 with book JSON on success.
        400 ``{"error": "..."}`` if the book is already active.
    """
    try:
        book = checkout_service.reactivate_book(barcode)
        return jsonify(book.to_dict())
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
