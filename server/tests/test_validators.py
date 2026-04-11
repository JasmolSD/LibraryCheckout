"""Tests for the VBA-ported validators."""

import pytest

from server.app.services.validators import (
    ValidationError,
    normalize_name,
    parse_checkout_prefix,
    validate_barcode,
    validate_card,
)


class TestBarcode:
    def test_accepts_10_digits(self):
        assert validate_barcode("1234567890") == "1234567890"

    def test_accepts_13_digits(self):
        # ISBN-13 is a valid barcode length
        assert validate_barcode("9780451524935") == "9780451524935"

    def test_accepts_14_digits(self):
        assert validate_barcode("12345678901234") == "12345678901234"

    def test_rejects_wrong_length(self):
        with pytest.raises(ValidationError):
            validate_barcode("123")

    def test_rejects_12_digits(self):
        with pytest.raises(ValidationError):
            validate_barcode("123456789012")

    def test_rejects_non_digits(self):
        with pytest.raises(ValidationError):
            validate_barcode("12345abcde")

    def test_rejects_empty(self):
        with pytest.raises(ValidationError):
            validate_barcode("")

    def test_rejects_none(self):
        with pytest.raises(ValidationError):
            validate_barcode(None)

    def test_strips_whitespace(self):
        assert validate_barcode("  1234567890  ") == "1234567890"


class TestPrefix:
    def test_3w_prefix(self):
        assert parse_checkout_prefix("3W1234567890") == ("1234567890", 3)

    def test_2w_prefix(self):
        assert parse_checkout_prefix("2W1234567890") == ("1234567890", 2)

    def test_no_prefix_defaults_to_3_weeks(self):
        assert parse_checkout_prefix("1234567890") == ("1234567890", 3)

    def test_lowercase_prefix(self):
        assert parse_checkout_prefix("3w1234567890") == ("1234567890", 3)


class TestName:
    def test_inserts_comma(self):
        assert normalize_name("john doe") == "JOHN, DOE"

    def test_preserves_existing_comma(self):
        assert normalize_name("DOE, JANE") == "DOE, JANE"

    def test_uppercases(self):
        assert normalize_name("smith, alice") == "SMITH, ALICE"

    def test_rejects_empty(self):
        with pytest.raises(ValidationError):
            normalize_name("")


class TestCard:
    def test_accepts_10_digits(self):
        assert validate_card("1234567890") == "1234567890"

    def test_accepts_14_digits(self):
        assert validate_card("12345678901234") == "12345678901234"

    def test_rejects_13_digits(self):
        # 13-digit ISBNs are valid barcodes but NOT valid card numbers
        with pytest.raises(ValidationError):
            validate_card("9780451524935")

    def test_rejects_wrong_length(self):
        with pytest.raises(ValidationError):
            validate_card("12345")

    def test_rejects_non_digits(self):
        with pytest.raises(ValidationError):
            validate_card("123456789X")

    def test_rejects_none(self):
        with pytest.raises(ValidationError):
            validate_card(None)
