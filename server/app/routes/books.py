"""Book catalog endpoints — add items and ISBN metadata lookup.

Blueprinted under ``/api/books``.  All responses are JSON.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from flask import Blueprint, jsonify, request

from ..services import checkout_service
from ..services.validators import ValidationError

bp = Blueprint("books", __name__, url_prefix="/api/books")

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "dvd": ["dvd", "video", "film", "movie", "motion picture"],
    "audiobook": ["audio", "spoken word", "sound recording"],
    "magazine": ["magazine", "periodical", "journal", "serial"],
    "ebook": ["electronic", "ebook", "e-book", "digital"],
}


def _map_category(raw_categories: list[str]) -> str:
    """Best-effort mapping from Google Books categories to our simplified set."""
    combined = " ".join(raw_categories).lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            return category
    return "book"


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


@bp.post("/")
def add_book():
    """Add a new item to the library catalog.

    Request body (JSON):
        barcode (str): ISBN-10, ISBN-13, or 14-digit library barcode.
        title (str, optional): Item title.
        author (str, optional): Author name(s).
        category (str, optional): One of book / dvd / audiobook / magazine /
            ebook / other.  Defaults to ``"book"``.

    Returns:
        201 with the new book JSON on success.
        400 ``{"error": "..."}`` on validation failure or duplicate barcode.
    """
    data = request.get_json() or {}
    try:
        book = checkout_service.add_book_to_catalog(
            barcode=data.get("barcode", ""),
            title=data.get("title"),
            author=data.get("author"),
            category=data.get("category", "book"),
        )
        return jsonify(book.to_dict()), 201
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
