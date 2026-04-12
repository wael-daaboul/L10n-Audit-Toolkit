import pytest
from pathlib import Path
from l10n_audit.reports.report_aggregator import old_value_for_issue

def test_old_value_for_issue_handles_nested_suffix_match():
    # Simulation of flattened JSON data
    en_data = {
        "messages.contact_with_us": "Contact Us",
        "home.title": "Home"
    }
    ar_data = {
        "messages.contact_with_us": "اتصل بنا",
    }
    
    # Issue only contains the short key
    issue = {
        "key": "contact_with_us",
        "locale": "en",
        "source": "en_locale_qc"
    }
    
    # Act
    value = old_value_for_issue(issue, en_data, ar_data)
    
    # Assert: Should match via suffix
    assert value == "Contact Us"

    # Test Arabic
    issue_ar = {
        "key": "contact_with_us",
        "locale": "ar",
        "source": "ar_locale_qc"
    }
    value_ar = old_value_for_issue(issue_ar, en_data, ar_data)
    assert value_ar == "اتصل بنا"

def test_old_value_for_issue_prefers_direct_match():
    en_data = {
        "contact_with_us": "Direct Match",
        "some.prefix.contact_with_us": "Suffix Match"
    }
    issue = {
        "key": "contact_with_us",
        "locale": "en"
    }
    value = old_value_for_issue(issue, en_data, {})
    assert value == "Direct Match"


def test_old_value_for_issue_uses_locale_context_when_issue_locale_is_missing():
    en_data = {
        "messages.auth.failed": "These credentials do not match our records.",
    }
    issue = {
        "key": "messages.auth.failed",
        "source": "localization",
    }

    value = old_value_for_issue(issue, en_data, {}, locale_context="en")

    assert value == "These credentials do not match our records."


def test_old_value_for_issue_rejects_ambiguous_suffix_match():
    en_data = {
        "messages.auth.failed": "Message failure",
        "validation.auth.failed": "Validation failure",
    }
    issue = {
        "key": "auth.failed",
        "locale": "en",
    }

    value = old_value_for_issue(issue, en_data, {})

    assert value == ""


def test_old_value_for_issue_does_not_cross_wrong_group_prefix():
    en_data = {
        "messages.auth.failed": "These credentials do not match our records.",
    }
    issue = {
        "key": "lang.auth.failed",
        "source": "localization",
    }

    value = old_value_for_issue(issue, en_data, {}, locale_context="en")

    assert value == ""
