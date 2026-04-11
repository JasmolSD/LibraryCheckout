"""Input validators — port of the VBA digit/length checks."""

from __future__ import annotations

VALID_LENGTHS = (10, 14)


class ValidationError(ValueError):
    pass


def validate_barcode(raw: str) -> str:
    """Strip whitespace, verify 10 or 14 digit length. Returns clean barcode."""
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


def validate_card(raw: str) -> str:
    """Library cards follow the same 10/14-digit rule as item barcodes."""
    return validate_barcode(raw)


def parse_checkout_prefix(raw: str) -> tuple[str, int]:
    """Port of VBA Select Case on '3W'/'2W' prefix.
    Returns (clean_barcode, weeks). Default = 3 weeks.
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
    """Port of VBA UCase + comma-insertion logic for 'LAST, FIRST' format."""
    if not raw or not raw.strip():
        raise ValidationError("Name is required")
    name = raw.strip().upper()
    if "," not in name and " " in name:
        # Insert comma after first space: "JOHN DOE" -> "JOHN, DOE"
        name = name.replace(" ", ", ", 1)
    return name
