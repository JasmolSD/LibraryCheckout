"""Input validators — port of the VBA digit/length checks.

All public functions raise :class:`ValidationError` (a :class:`ValueError`
subclass) on invalid input and return a cleaned string on success.
They accept ``None`` as input so that callers may pass ``request.get_json()``
values directly without pre-checking for ``None``.
"""

from __future__ import annotations

VALID_LENGTHS = (10, 14)


class ValidationError(ValueError):
    """Raised by validator and service functions for user-facing input errors.

    Callers should catch this and return an HTTP 400 response with the
    exception message as the ``"error"`` field.
    """


def validate_barcode(raw: str | None) -> str:
    """Strip whitespace and verify the value is a 10- or 14-digit barcode.

    Args:
        raw: Raw barcode string from user input or API request, or ``None``.

    Returns:
        The cleaned barcode string with leading/trailing whitespace removed.

    Raises:
        ValidationError: If ``raw`` is ``None``, empty, non-numeric, or has
            the wrong length.
    """
    if raw is None:
        raise ValidationError("Barcode is required")
    cleaned = str(raw).strip()
    if not cleaned:
        raise ValidationError("Barcode cannot be empty")
    if not cleaned.isdigit():
        raise ValidationError("Barcode must contain only digits")
    if len(cleaned) not in VALID_LENGTHS:
        raise ValidationError(f"Barcode must be {' or '.join(map(str, VALID_LENGTHS))} digits")
    return cleaned


def validate_card(raw: str | None) -> str:
    """Validate a library card number using the same rules as item barcodes.

    Library card numbers must be exactly 10 or 14 digits (matching the legacy
    VBA implementation).

    Args:
        raw: Raw card number from user input or API request, or ``None``.

    Returns:
        The cleaned card number string.

    Raises:
        ValidationError: Delegated from :func:`validate_barcode`.
    """
    return validate_barcode(raw)


def parse_checkout_prefix(raw: str | None) -> tuple[str, int]:
    """Parse an optional week prefix from a barcode string and return the period.

    Ported from the VBA ``Select Case`` on ``"3W"`` / ``"2W"`` prefix.
    The prefix is case-insensitive.

    Recognised prefixes:
        * ``1W`` — 1-week loan period
        * ``2W`` — 2-week loan period
        * ``3W`` — 3-week loan period (same as no prefix)
        * *(none)* — defaults to 3 weeks

    Args:
        raw: Raw scanner / keyboard input, or ``None``.

    Returns:
        A ``(clean_barcode, weeks)`` tuple where ``clean_barcode`` has been
        validated by :func:`validate_barcode`.

    Raises:
        ValidationError: If ``raw`` is ``None`` or the barcode portion is invalid.
    """
    if raw is None:
        raise ValidationError("Item is required")
    s = str(raw).strip()
    upper = s.upper()
    if upper.startswith("3W"):
        return validate_barcode(s[2:]), 3
    if upper.startswith("2W"):
        return validate_barcode(s[2:]), 2
    if upper.startswith("1W"):
        return validate_barcode(s[2:]), 1
    return validate_barcode(s), 3


def normalize_name(raw: str) -> str:
    """Normalise a patron name to upper-case "LAST, FIRST" format.

    Ported from the VBA ``UCase`` + comma-insertion logic.  Accepts either
    ``"LAST, FIRST"`` (unchanged except for upper-casing) or ``"First Last"``
    (space is converted to ``", "`` after the first word).

    Args:
        raw: Raw name string from user input.

    Returns:
        Upper-cased name in ``"LAST, FIRST"`` format.

    Raises:
        ValidationError: If ``raw`` is empty or whitespace-only.
    """
    if not raw or not raw.strip():
        raise ValidationError("Name is required")
    name = raw.strip().upper()
    if "," not in name and " " in name:
        # Insert comma after first space: "JOHN DOE" -> "JOHN, DOE"
        name = name.replace(" ", ", ", 1)
    return name
