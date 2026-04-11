"""Input validators — port of the VBA digit/length checks.

All public functions raise :class:`ValidationError` (a :class:`ValueError`
subclass) on invalid input and return a cleaned string on success.
They accept ``None`` as input so that callers may pass ``request.get_json()``
values directly without pre-checking for ``None``.
"""

from __future__ import annotations

VALID_LENGTHS = (10, 13, 14)      # 13 = ISBN-13; 10 = ISBN-10 / legacy; 14 = EAN-14
VALID_CARD_LENGTHS = (10, 14)     # library card numbers never use ISBN-13 length


class ValidationError(ValueError):
    """Raised by validator and service functions for user-facing input errors.

    Callers should catch this and return an HTTP 400 response with the
    exception message as the ``"error"`` field.
    """


def validate_barcode(raw: str | None) -> str:
    """Strip whitespace and verify the value is a 10-, 13-, or 14-digit barcode.

    Accepts ISBN-10 (10 digits), ISBN-13 (13 digits), and EAN-14 (14 digits).

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
    """Validate a library card number (10 or 14 digits only — not ISBN-13 length).

    Args:
        raw: Raw card number from user input or API request, or ``None``.

    Returns:
        The cleaned card number string.

    Raises:
        ValidationError: If the card number is invalid.
    """
    if raw is None:
        raise ValidationError("Card number is required")
    cleaned = str(raw).strip()
    if not cleaned:
        raise ValidationError("Card number cannot be empty")
    if not cleaned.isdigit():
        raise ValidationError("Card number must contain only digits")
    if len(cleaned) not in VALID_CARD_LENGTHS:
        raise ValidationError(
            f"Card number must be {' or '.join(map(str, VALID_CARD_LENGTHS))} digits"
        )
    return cleaned


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
