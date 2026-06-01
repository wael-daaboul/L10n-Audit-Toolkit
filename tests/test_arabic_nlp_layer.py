"""tests/test_arabic_nlp_layer.py

Unit tests for the Arabic NLP layer (l10n_audit/core/arabic_nlp_layer.py).

The module is designed to be always-callable: it must never raise and must
always return all 8 camel_* fields as strings, regardless of whether
camel-tools is installed.

Tests are written to pass in both scenarios:
  A) camel-tools NOT installed (primary CI path — pure-Python fallback)
  B) camel-tools installed (real backend path)

Each test documents which assertions differ between scenarios.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch

from l10n_audit.core.arabic_nlp_layer import (
    analyze_arabic_text,
    RESULT_FIELDS,
    _CAMEL_TOOLS_AVAILABLE,
    _detect_mixed_script,
    _normalize_arabic_text,
    _is_arabic_text,
)

# ---------------------------------------------------------------------------
# Shared expected field names
# ---------------------------------------------------------------------------

EXPECTED_FIELDS = (
    "camel_available",
    "camel_reason",
    "camel_mixed_script",
    "camel_unknown_count",
    "camel_unknown_tokens",
    "camel_pos_summary",
    "camel_dialect",
    "camel_normalized_preview",
)


# ---------------------------------------------------------------------------
# Helper: assert that a result dict is structurally valid
# ---------------------------------------------------------------------------

def _assert_valid_result(result: dict, label: str = "") -> None:
    prefix = f"[{label}] " if label else ""
    assert isinstance(result, dict), f"{prefix}result must be a dict"
    for field in EXPECTED_FIELDS:
        assert field in result, f"{prefix}missing field {field!r}"
        assert isinstance(result[field], str), (
            f"{prefix}field {field!r} must be a str, got {type(result[field])!r}"
        )


# ===========================================================================
# Group 1: RESULT_FIELDS constant
# ===========================================================================

def test_result_fields_constant_matches_expected():
    assert set(RESULT_FIELDS) == set(EXPECTED_FIELDS)
    assert len(RESULT_FIELDS) == 8


# ===========================================================================
# Group 2: Structural contract — all inputs produce valid dicts
# ===========================================================================

@pytest.mark.parametrize("text", [
    "مرحبا بالعالم",
    "Hello world",
    "مرحبا Hello mixed",
    "",
    "   ",
    "123",
    "مرحبا 123",
    "\u0020\u00a0",        # whitespace-only variants
    "!@#$%^",
])
def test_always_returns_all_fields(text):
    result = analyze_arabic_text(text)
    _assert_valid_result(result, label=repr(text))


def test_none_input_returns_valid_result():
    result = analyze_arabic_text(None)  # type: ignore[arg-type]
    _assert_valid_result(result, label="None")


def test_non_string_input_coerced():
    for value in (42, 3.14, [], {}, object()):
        result = analyze_arabic_text(value)  # type: ignore[arg-type]
        _assert_valid_result(result, label=str(type(value)))


def test_result_values_are_all_strings():
    for text in ["مرحبا", "Hello", "", None]:
        result = analyze_arabic_text(text)  # type: ignore[arg-type]
        for key, val in result.items():
            assert isinstance(val, str), (
                f"Field {key!r} is not a str for input {text!r}: {val!r}"
            )


# ===========================================================================
# Group 3: camel_available field
# ===========================================================================

def test_camel_available_is_yes_or_no():
    result = analyze_arabic_text("مرحبا")
    assert result["camel_available"] in ("yes", "no"), (
        f"camel_available must be 'yes' or 'no', got {result['camel_available']!r}"
    )


def test_camel_available_matches_module_flag():
    result = analyze_arabic_text("مرحبا")
    expected = "yes" if _CAMEL_TOOLS_AVAILABLE else "no"
    assert result["camel_available"] == expected


def test_camel_available_empty_text():
    result = analyze_arabic_text("")
    # Even for empty text the availability flag is reported
    assert result["camel_available"] in ("yes", "no")


def test_camel_available_non_arabic():
    result = analyze_arabic_text("Hello World")
    assert result["camel_available"] in ("yes", "no")


# ===========================================================================
# Group 4: camel_reason field
# ===========================================================================

def test_reason_non_empty_for_arabic_text():
    result = analyze_arabic_text("مرحبا بالعالم")
    assert result["camel_reason"] != "", "camel_reason must not be empty for Arabic text"


def test_reason_empty_text():
    result = analyze_arabic_text("")
    assert result["camel_reason"] == "empty-text"


def test_reason_non_arabic_text():
    result = analyze_arabic_text("Hello")
    assert result["camel_reason"] == "not-arabic-text"


def test_reason_whitespace_only():
    result = analyze_arabic_text("   ")
    assert result["camel_reason"] == "empty-text"


def test_reason_when_camel_unavailable():
    """When camel-tools is absent the reason must report unavailability."""
    with patch(
        "l10n_audit.core.arabic_nlp_layer._CAMEL_TOOLS_AVAILABLE", False
    ):
        result = analyze_arabic_text("مرحبا")
        assert "unavailable" in result["camel_reason"].lower() or \
               "camel" in result["camel_reason"].lower(), (
            f"Expected unavailability note, got: {result['camel_reason']!r}"
        )


# ===========================================================================
# Group 5: camel_mixed_script field
# ===========================================================================

@pytest.mark.parametrize("text, expected", [
    ("مرحبا بالعالم",         "no"),    # pure Arabic
    ("Hello World",           "no"),    # pure Latin (no Arabic)
    ("مرحبا Hello",           "yes"),   # mixed
    ("مرحبا 123",             "no"),    # digits not Latin alpha
    ("",                      ""),      # empty → no value
    ("نعم Yes",               "yes"),   # explicit mixed
])
def test_mixed_script_detection(text, expected):
    result = analyze_arabic_text(text)
    assert result["camel_mixed_script"] == expected, (
        f"For {text!r}: expected mixed_script={expected!r}, "
        f"got {result['camel_mixed_script']!r}"
    )


def test_mixed_script_helper_directly():
    assert _detect_mixed_script("مرحبا Hello") == "yes"
    assert _detect_mixed_script("مرحبا") == "no"
    assert _detect_mixed_script("Hello") == "no"
    assert _detect_mixed_script("") == ""


# ===========================================================================
# Group 6: camel_normalized_preview field
# ===========================================================================

def test_normalized_preview_arabic_text():
    result = analyze_arabic_text("مَرْحَباً بِالعَالَمِ")  # text with diacritics
    preview = result["camel_normalized_preview"]
    assert isinstance(preview, str)
    # Diacritics should be stripped in the fallback path
    if not _CAMEL_TOOLS_AVAILABLE:
        # No harakat characters should remain
        import re
        assert not re.search(r"[\u064B-\u065F\u0670]", preview), (
            "Diacritics should be stripped in normalised preview"
        )


def test_normalized_preview_empty_text():
    result = analyze_arabic_text("")
    assert result["camel_normalized_preview"] == ""


def test_normalized_preview_non_arabic_text():
    result = analyze_arabic_text("Hello World")
    # For non-Arabic text camel_normalized_preview is empty
    assert result["camel_normalized_preview"] == ""


def test_normalized_preview_max_length():
    long_text = "مرحبا " * 100  # well over 120 chars
    result = analyze_arabic_text(long_text)
    assert len(result["camel_normalized_preview"]) <= 120


def test_normalize_arabic_text_helper():
    text_with_diacritics = "مَرْحَبًا"
    normalized = _normalize_arabic_text(text_with_diacritics)
    assert isinstance(normalized, str)
    import re
    assert not re.search(r"[\u064B-\u065F\u0670]", normalized)


def test_normalize_arabic_text_alef_normalization():
    # All Alef variants should normalize to bare Alef (ا)
    variants = "إأآا"
    normalized = _normalize_arabic_text(variants)
    assert "إ" not in normalized
    assert "أ" not in normalized
    assert "آ" not in normalized


# ===========================================================================
# Group 7: camel_unknown_count, camel_unknown_tokens, camel_pos_summary
# ===========================================================================

def test_unknown_count_is_string_integer_or_empty():
    result = analyze_arabic_text("مرحبا بالعالم")
    val = result["camel_unknown_count"]
    assert isinstance(val, str)
    if val:
        # Must be parseable as int when non-empty
        int(val)  # raises ValueError if not int-string → test fails


def test_unknown_tokens_is_space_joined_or_empty():
    result = analyze_arabic_text("مرحبا بالعالم")
    val = result["camel_unknown_tokens"]
    assert isinstance(val, str)
    # No newlines
    assert "\n" not in val


def test_pos_summary_is_space_joined_or_empty():
    result = analyze_arabic_text("مرحبا بالعالم")
    val = result["camel_pos_summary"]
    assert isinstance(val, str)
    assert "\n" not in val


def test_no_pos_for_non_arabic_text():
    result = analyze_arabic_text("Hello World")
    assert result["camel_pos_summary"] == ""
    assert result["camel_unknown_count"] == ""
    assert result["camel_unknown_tokens"] == ""


# ===========================================================================
# Group 8: camel_dialect field
# ===========================================================================

def test_dialect_disabled_by_default():
    result = analyze_arabic_text("مرحبا بالعالم")
    # When enable_dialect=False dialect should be ""
    assert result["camel_dialect"] == ""


def test_dialect_empty_when_disabled_explicitly():
    result = analyze_arabic_text("مرحبا", enable_dialect=False)
    assert result["camel_dialect"] == ""


def test_dialect_is_string_when_enabled():
    result = analyze_arabic_text("مرحبا", enable_dialect=True)
    assert isinstance(result["camel_dialect"], str)
    # When camel-tools is unavailable it must remain empty
    if not _CAMEL_TOOLS_AVAILABLE:
        assert result["camel_dialect"] == ""


# ===========================================================================
# Group 9: Failure safety
# ===========================================================================

def test_never_raises_on_bad_input():
    bad_inputs = [None, "", "   ", "Hello", "مرحبا", 0, [], {}, b"bytes"]
    for inp in bad_inputs:
        try:
            result = analyze_arabic_text(inp)  # type: ignore[arg-type]
            _assert_valid_result(result, label=str(inp))
        except Exception as exc:
            pytest.fail(
                f"analyze_arabic_text({inp!r}) raised {type(exc).__name__}: {exc}"
            )


def test_internal_camel_error_falls_back_gracefully():
    """Simulate a failure inside _camel_analyze — result must still be valid."""
    with patch(
        "l10n_audit.core.arabic_nlp_layer._camel_analyze",
        side_effect=RuntimeError("simulated crash"),
    ):
        # Only relevant when camel_tools would be "available"
        with patch("l10n_audit.core.arabic_nlp_layer._CAMEL_TOOLS_AVAILABLE", True):
            result = analyze_arabic_text("مرحبا")
    _assert_valid_result(result, label="simulated crash")
    assert result["camel_available"] == "no"  # falls back to _fallback_result


# ===========================================================================
# Group 10: Integration with camel_decorator._analyse_row
# ===========================================================================

def test_analyse_row_integration():
    """_analyse_row must call analyze_arabic_text on old_value."""
    from l10n_audit.core.camel_decorator import _analyse_row, CAMEL_FIELDS

    row = {
        "key": "greeting",
        "locale": "ar",
        "old_value": "مرحبا بالعالم",
        "suggested_fix": "مرحبا.",
        "approved_new": "",
    }
    result = _analyse_row(row)
    for field in CAMEL_FIELDS:
        assert field in result, f"_analyse_row missing field {field!r}"
        assert isinstance(result[field], str), f"field {field!r} must be str"


def test_analyse_row_fallback_to_source_old_value():
    """When old_value is absent, _analyse_row falls back to source_old_value."""
    from l10n_audit.core.camel_decorator import _analyse_row

    row = {
        "key": "greeting",
        "locale": "ar",
        "source_old_value": "مرحبا",
    }
    result = _analyse_row(row)
    assert isinstance(result, dict)
    assert "camel_available" in result


def test_analyse_row_empty_old_value():
    """Empty old_value must not raise — all fields returned."""
    from l10n_audit.core.camel_decorator import _analyse_row, CAMEL_FIELDS

    row = {"key": "k1", "locale": "ar", "old_value": ""}
    result = _analyse_row(row)
    for field in CAMEL_FIELDS:
        assert field in result


def test_analyse_row_does_not_mutate_input():
    """_analyse_row must never mutate the input row dict."""
    from l10n_audit.core.camel_decorator import _analyse_row

    row = {"key": "k", "old_value": "نعم", "approved_new": "some_value"}
    original_keys = set(row.keys())
    original_values = dict(row)

    _analyse_row(row)

    assert set(row.keys()) == original_keys, "_analyse_row added keys to input row"
    for k, v in original_values.items():
        assert row[k] == v, f"_analyse_row mutated row[{k!r}]"


# ===========================================================================
# Group 11: is_arabic_text helper
# ===========================================================================

@pytest.mark.parametrize("text, expected", [
    ("مرحبا",         True),
    ("Hello",         False),
    ("",              False),
    ("123",           False),
    ("مرحبا Hello",   True),   # contains Arabic → True
    ("!؟",            False),  # Arabic punctuation alone is not Arabic text
])
def test_is_arabic_text(text, expected):
    assert _is_arabic_text(text) == expected
