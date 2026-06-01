"""
Step 5 regression tests: relaxed review row validation.

Validates that:
- locale "fr" (or any non-empty locale) is accepted
- rows with missing/None message still validate when otherwise valid
- empty locale string is still rejected (truly required field)
- truly required fields (key, issue_type, current_value, candidate_value,
  generated_at) are still enforced
"""
from __future__ import annotations

from l10n_audit.fixes.fix_merger import validate_review_row


def _valid_row(**overrides) -> dict:
    base = {
        "key": "hello",
        "locale": "ar",
        "issue_type": "missing_translation",
        "message": "Needs translation",
        "current_value": "مرحبا",
        "candidate_value": "أهلاً",
        "generated_at": "2026-03-08T00:00:00+00:00",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Locale validation: accept any non-empty string
# ---------------------------------------------------------------------------

def test_locale_fr_is_accepted() -> None:
    """locale='fr' must be accepted — not just 'ar' and 'en'."""
    is_valid, missing = validate_review_row(_valid_row(locale="fr"))
    assert is_valid is True, f"locale='fr' must be valid, got missing={missing}"
    assert "locale" not in missing


def test_locale_de_is_accepted() -> None:
    is_valid, missing = validate_review_row(_valid_row(locale="de"))
    assert is_valid is True, f"locale='de' must be valid"


def test_locale_zh_CN_is_accepted() -> None:
    is_valid, missing = validate_review_row(_valid_row(locale="zh-CN"))
    assert is_valid is True


def test_locale_en_still_accepted() -> None:
    is_valid, missing = validate_review_row(_valid_row(locale="en"))
    assert is_valid is True


def test_locale_ar_still_accepted() -> None:
    is_valid, missing = validate_review_row(_valid_row(locale="ar"))
    assert is_valid is True


def test_empty_locale_still_rejected() -> None:
    """Empty locale string must still be rejected — it is a required field."""
    is_valid, missing = validate_review_row(_valid_row(locale=""))
    assert is_valid is False
    assert "locale" in missing


def test_none_locale_still_rejected() -> None:
    is_valid, missing = validate_review_row(_valid_row(locale=None))
    assert is_valid is False
    assert "locale" in missing


# ---------------------------------------------------------------------------
# Message field: optional
# ---------------------------------------------------------------------------

def test_row_without_message_is_valid() -> None:
    """message is optional. A row without message must still pass validation."""
    row = _valid_row()
    del row["message"]
    is_valid, missing = validate_review_row(row)
    assert is_valid is True, f"Row without 'message' must be valid, got missing={missing}"
    assert "message" not in missing


def test_row_with_none_message_is_valid() -> None:
    is_valid, missing = validate_review_row(_valid_row(message=None))
    assert is_valid is True, f"message=None must be valid, got missing={missing}"
    assert "message" not in missing


def test_row_with_empty_message_is_valid() -> None:
    is_valid, missing = validate_review_row(_valid_row(message=""))
    assert is_valid is True, f"message='' must be valid, got missing={missing}"


# ---------------------------------------------------------------------------
# Truly required fields are still enforced
# ---------------------------------------------------------------------------

def test_missing_key_still_rejected() -> None:
    is_valid, missing = validate_review_row(_valid_row(key=None))
    assert is_valid is False
    assert "key" in missing


def test_missing_issue_type_still_rejected() -> None:
    is_valid, missing = validate_review_row(_valid_row(issue_type=None))
    assert is_valid is False
    assert "issue_type" in missing


def test_missing_current_value_still_rejected() -> None:
    is_valid, missing = validate_review_row(_valid_row(current_value=None))
    assert is_valid is False
    assert "current_value" in missing


def test_missing_candidate_value_still_rejected() -> None:
    is_valid, missing = validate_review_row(_valid_row(candidate_value=None))
    assert is_valid is False
    assert "candidate_value" in missing


def test_missing_generated_at_still_rejected() -> None:
    is_valid, missing = validate_review_row(_valid_row(generated_at=None))
    assert is_valid is False
    assert "generated_at" in missing
