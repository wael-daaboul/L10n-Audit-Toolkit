"""
tests/test_languagetool_layer.py
=================================
Unit tests for l10n_audit/core/languagetool_layer.py
Phase 1 / Step 1 — isolated layer.
Phase 1 / Step 2 — signal alignment bridge (lt_findings_to_signal_dict).

All tests are fully isolated: they use monkeypatching and in-process stubs.
No real Java runtime, real LT server, or real file I/O is required.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from l10n_audit.core.languagetool_layer import (
    LTFinding,
    LanguageToolLayer,
    classify_simple_issue,
    get_languagetool_layer,
    lt_findings_to_signal_dict,
)
from l10n_audit.core.languagetool_manager import LanguageToolSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runtime() -> SimpleNamespace:
    """Minimal runtime stub — only the attributes consumed by LanguageTool."""
    return SimpleNamespace(
        tools_dir=None,
        project_root=None,
        languagetool_configured_dir=None,
    )


def _make_fake_category(id_: str) -> SimpleNamespace:
    return SimpleNamespace(id=id_)


def _make_fake_replacement(value: str) -> SimpleNamespace:
    return SimpleNamespace(value=value)


def _make_fake_match(
    *,
    category_id: str = "GRAMMAR",
    rule_id: str = "RULE_001",
    message: str = "Test message",
    replacements: list[str] | None = None,
    offset: int = 0,
    error_length: int = 5,
    context: str = "",
) -> SimpleNamespace:
    """Build a fake language_tool_python match object."""
    raw_replacements = [_make_fake_replacement(r) for r in (replacements or [])]
    return SimpleNamespace(
        category=_make_fake_category(category_id),
        ruleId=rule_id,
        message=message,
        replacements=raw_replacements,
        offset=offset,
        errorLength=error_length,
        context=context,
    )


def _make_fake_tool(matches: list[Any]) -> SimpleNamespace:
    """Fake LT tool whose .check() always returns the given matches."""
    return SimpleNamespace(
        check=lambda text: matches,
        close=lambda: None,
    )


def _make_session(tool: Any | None) -> LanguageToolSession:
    mode = "LanguageTool mode: local bundled server" if tool else "rule-based"
    note = "" if tool else "LT unavailable (stub)"
    return LanguageToolSession(tool=tool, mode=mode, note=note)


# ---------------------------------------------------------------------------
# 1.  get_languagetool_layer — returns None when Java is absent
# ---------------------------------------------------------------------------


def test_get_layer_returns_none_when_java_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "l10n_audit.core.languagetool_layer.check_java_available",
        lambda: False,
    )
    runtime = _make_runtime()
    layer = get_languagetool_layer(runtime, "en-US")
    assert layer is None


# ---------------------------------------------------------------------------
# 2.  get_languagetool_layer — returns None when session.tool is None
# ---------------------------------------------------------------------------


def test_get_layer_returns_none_when_session_has_no_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "l10n_audit.core.languagetool_layer.check_java_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "l10n_audit.core.languagetool_layer.create_language_tool_session",
        lambda lang, rt, **kw: _make_session(tool=None),
    )
    runtime = _make_runtime()
    layer = get_languagetool_layer(runtime, "en-US")
    assert layer is None


# ---------------------------------------------------------------------------
# 3.  get_languagetool_layer — returns None when session creation raises
# ---------------------------------------------------------------------------


def test_get_layer_returns_none_when_session_creation_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "l10n_audit.core.languagetool_layer.check_java_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "l10n_audit.core.languagetool_layer.create_language_tool_session",
        lambda lang, rt, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    runtime = _make_runtime()
    layer = get_languagetool_layer(runtime, "en-US")
    assert layer is None


# ---------------------------------------------------------------------------
# 4.  get_languagetool_layer — returns a LanguageToolLayer when tool is present
# ---------------------------------------------------------------------------


def test_get_layer_returns_layer_when_tool_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_tool = _make_fake_tool([])
    monkeypatch.setattr(
        "l10n_audit.core.languagetool_layer.check_java_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "l10n_audit.core.languagetool_layer.create_language_tool_session",
        lambda lang, rt, **kw: _make_session(tool=fake_tool),
    )
    runtime = _make_runtime()
    layer = get_languagetool_layer(runtime, "en-US")
    assert isinstance(layer, LanguageToolLayer)
    layer.close()


# ---------------------------------------------------------------------------
# 5.  analyze_text_batch — empty input returns empty list
# ---------------------------------------------------------------------------


def test_analyze_batch_empty_input() -> None:
    fake_tool = _make_fake_tool([])
    session = _make_session(tool=fake_tool)
    layer = LanguageToolLayer(session, "en-US")
    result = layer.analyze_text_batch([])
    assert result == []
    layer.close()


# ---------------------------------------------------------------------------
# 6.  analyze_text_batch — whitespace-only text is skipped
# ---------------------------------------------------------------------------


def test_analyze_batch_skips_whitespace_only_text() -> None:
    fake_tool = _make_fake_tool([])
    session = _make_session(tool=fake_tool)
    layer = LanguageToolLayer(session, "en-US")
    result = layer.analyze_text_batch([("key.a", "   "), ("key.b", "")])
    assert result == []
    layer.close()


# ---------------------------------------------------------------------------
# 7.  analyze_text_batch — normalized findings have correct fields
# ---------------------------------------------------------------------------


def test_analyze_batch_normalizes_finding_fields() -> None:
    original = "Your payment is failed"
    replacement = "Your payment failed"
    match = _make_fake_match(
        category_id="GRAMMAR",
        rule_id="EN_SPECIFIC_CASE",
        message="  Passive  voice  issue  ",
        replacements=["Your payment failed"],
        offset=0,
        error_length=len(original),
        context=original,
    )
    fake_tool = _make_fake_tool([match])
    session = _make_session(tool=fake_tool)
    layer = LanguageToolLayer(session, "en-US")

    result = layer.analyze_text_batch([("login.title", original)])

    assert len(result) == 1
    finding = result[0]
    assert isinstance(finding, LTFinding)
    assert finding.key == "login.title"
    assert finding.rule_id == "EN_SPECIFIC_CASE"
    assert finding.issue_category == "grammar"          # must be lowercased
    assert finding.message == "Passive voice issue"     # whitespace collapsed
    assert finding.original_text == original
    assert finding.suggested_text == replacement
    assert finding.offset == 0
    assert finding.error_length == len(original)
    assert finding.is_simple_fix is True
    layer.close()


# ---------------------------------------------------------------------------
# 8.  analyze_text_batch — no replacements → suggested_text is empty string
# ---------------------------------------------------------------------------


def test_analyze_batch_no_replacements_gives_empty_suggested_text() -> None:
    match = _make_fake_match(
        category_id="GRAMMAR",
        rule_id="SOME_RULE",
        message="Something wrong",
        replacements=[],   # ← no replacements
        offset=3,
        error_length=4,
    )
    fake_tool = _make_fake_tool([match])
    session = _make_session(tool=fake_tool)
    layer = LanguageToolLayer(session, "en-US")

    result = layer.analyze_text_batch([("key.x", "bad text here")])

    assert len(result) == 1
    assert result[0].suggested_text == ""
    layer.close()


# ---------------------------------------------------------------------------
# 9.  analyze_text_batch — per-item check exception is swallowed gracefully
# ---------------------------------------------------------------------------


def test_analyze_batch_swallows_per_item_check_error() -> None:
    def _exploding_check(text: str) -> list:
        raise RuntimeError("LT internal error")

    fake_tool = SimpleNamespace(check=_exploding_check, close=lambda: None)
    session = _make_session(tool=fake_tool)
    layer = LanguageToolLayer(session, "en-US")

    result = layer.analyze_text_batch([("key.a", "some text")])

    assert result == []
    layer.close()


# ---------------------------------------------------------------------------
# 9b. analyze_text_batch — per-item check exception is raised in strict mode
# ---------------------------------------------------------------------------


def test_analyze_batch_raises_per_item_check_error_in_strict_mode() -> None:
    def _exploding_check(text: str) -> list:
        raise RuntimeError("LT internal error")

    fake_tool = SimpleNamespace(check=_exploding_check, close=lambda: None)
    session = _make_session(tool=fake_tool)
    layer = LanguageToolLayer(session, "en-US")

    with pytest.raises(RuntimeError, match="LT internal error"):
        layer.analyze_text_batch([("key.a", "some text")], strict=True)
        
    layer.close()


# ---------------------------------------------------------------------------
# 10.  analyze_text_batch — multiple keys, multiple matches
# ---------------------------------------------------------------------------


def test_analyze_batch_multiple_keys_and_matches() -> None:
    match_a = _make_fake_match(category_id="TYPOS", rule_id="R_A",
                               message="Typo", replacements=["fixed"],
                               offset=0, error_length=3)
    match_b = _make_fake_match(category_id="GRAMMAR", rule_id="R_B",
                               message="Grammar issue", replacements=[],
                               offset=0, error_length=5)

    call_count = 0
    def _check(text: str) -> list:
        nonlocal call_count
        call_count += 1
        return [match_a] if call_count == 1 else [match_b]

    fake_tool = SimpleNamespace(check=_check, close=lambda: None)
    session = _make_session(tool=fake_tool)
    layer = LanguageToolLayer(session, "en-US")

    result = layer.analyze_text_batch([
        ("key.one", "typ error"),
        ("key.two", "is failed"),
    ])

    assert len(result) == 2
    assert result[0].key == "key.one"
    assert result[1].key == "key.two"
    layer.close()


# ---------------------------------------------------------------------------
# 11.  classify_simple_issue — simple categories return True
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("category", [
    "grammar",
    "Grammar",
    "GRAMMAR",
    "typos",
    "TYPOS",
    "spelling",
    "SPELLING",
    "whitespace",
    "WHITESPACE",
    "  grammar  ",     # leading/trailing whitespace
])
def test_classify_simple_issue_true_for_simple_categories(category: str) -> None:
    assert classify_simple_issue(category) is True


# ---------------------------------------------------------------------------
# 12.  classify_simple_issue — non-simple / unknown categories return False
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("category", [
    "style",
    "STYLE",
    "typography",
    "TYPOGRAPHY",
    "punctuation",
    "PUNCTUATION",
    "confused_words",
    "CONFUSED_WORDS",
    "semantics",
    "SEMANTICS",
    "",
    "unknown",
    "UNKNOWN",
    "miscellaneous",
])
def test_classify_simple_issue_false_for_non_simple_categories(
    category: str,
) -> None:
    assert classify_simple_issue(category) is False


# ---------------------------------------------------------------------------
# 13.  LanguageToolLayer.close — safe to call multiple times
# ---------------------------------------------------------------------------


def test_close_is_idempotent() -> None:
    closed_count = 0

    def _counting_close() -> None:
        nonlocal closed_count
        closed_count += 1

    fake_tool = SimpleNamespace(check=lambda t: [], close=_counting_close)
    session = _make_session(tool=fake_tool)
    layer = LanguageToolLayer(session, "en-US")

    layer.close()
    layer.close()
    layer.close()

    # The underlying session.close() should be invoked exactly once
    assert closed_count == 1


# ---------------------------------------------------------------------------
# 14.  LanguageToolLayer.close — does not raise on session.close() error
# ---------------------------------------------------------------------------


def test_close_swallows_session_close_error() -> None:
    def _bad_close() -> None:
        raise RuntimeError("session close exploded")

    fake_tool = SimpleNamespace(check=lambda t: [], close=_bad_close)
    session = _make_session(tool=fake_tool)
    layer = LanguageToolLayer(session, "en-US")
    layer.close()   # must not raise


# ---------------------------------------------------------------------------
# 15.  LTFinding dataclass — is a proper dataclass with expected fields
# ---------------------------------------------------------------------------


def test_lt_finding_is_dataclass_with_expected_fields() -> None:
    finding = LTFinding(
        key="k",
        rule_id="R",
        issue_category="grammar",
        message="msg",
        original_text="orig",
        suggested_text="sugg",
        offset=0,
        error_length=4,
        is_simple_fix=True,
    )
    assert finding.key == "k"
    assert finding.rule_id == "R"
    assert finding.issue_category == "grammar"
    assert finding.message == "msg"
    assert finding.original_text == "orig"
    assert finding.suggested_text == "sugg"
    assert finding.offset == 0
    assert finding.error_length == 4
    assert finding.is_simple_fix is True


# ---------------------------------------------------------------------------
# 16.  No file I/O, no report writing
#      (structural: just verify analyze_text_batch returns only LTFinding list)
# ---------------------------------------------------------------------------


def test_analyze_batch_returns_only_lt_finding_list() -> None:
    match = _make_fake_match(category_id="GRAMMAR", replacements=["fixed"])
    fake_tool = _make_fake_tool([match])
    session = _make_session(tool=fake_tool)
    layer = LanguageToolLayer(session, "en-US")

    result = layer.analyze_text_batch([("k", "some bad text here")])

    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, LTFinding)
    layer.close()


# ===========================================================================
# Phase 1 / Step 2 — lt_findings_to_signal_dict tests
# ===========================================================================


def _make_finding(
    key: str = "k",
    issue_category: str = "grammar",
    rule_id: str = "R001",
) -> LTFinding:
    """Helper: construct a minimal LTFinding from keyword args."""
    return LTFinding(
        key=key,
        rule_id=rule_id,
        issue_category=issue_category,
        message="test",
        original_text="original",
        suggested_text="suggested",
        offset=0,
        error_length=4,
        is_simple_fix=classify_simple_issue(issue_category),
    )


# ---------------------------------------------------------------------------
# S1.  Empty findings list → empty dict
# ---------------------------------------------------------------------------


def test_lt_findings_to_signal_dict_empty_input() -> None:
    result = lt_findings_to_signal_dict([])
    assert result == {}


# ---------------------------------------------------------------------------
# S2.  Output keys match build_language_tool_python_signals exactly
# ---------------------------------------------------------------------------


def test_lt_findings_to_signal_dict_output_shape() -> None:
    finding = _make_finding(key="k.a", issue_category="grammar", rule_id="R1")
    result = lt_findings_to_signal_dict([finding])

    assert "k.a" in result
    sig = result["k.a"]

    # Field names must be identical to build_language_tool_python_signals output
    assert set(sig.keys()) == {
        "lt_style_flags",
        "lt_grammar_flags",
        "lt_literalness_support",
        "lt_rule_ids",
        "sources",
    }
    # Types must match
    assert isinstance(sig["lt_style_flags"], int)
    assert isinstance(sig["lt_grammar_flags"], int)
    assert isinstance(sig["lt_literalness_support"], bool)
    assert isinstance(sig["lt_rule_ids"], list)
    assert isinstance(sig["sources"], list)


# ---------------------------------------------------------------------------
# S3.  Grammar category increments lt_grammar_flags, not lt_style_flags
# ---------------------------------------------------------------------------


def test_lt_findings_grammar_increments_grammar_counter() -> None:
    findings = [
        _make_finding(key="k.a", issue_category="grammar", rule_id="R1"),
        _make_finding(key="k.a", issue_category="grammar", rule_id="R2"),
    ]
    result = lt_findings_to_signal_dict(findings)

    sig = result["k.a"]
    assert sig["lt_grammar_flags"] == 2
    assert sig["lt_style_flags"] == 0
    assert sig["lt_literalness_support"] is False


# ---------------------------------------------------------------------------
# S4.  Style category increments lt_style_flags AND sets lt_literalness_support
# ---------------------------------------------------------------------------


def test_lt_findings_style_increments_style_counter() -> None:
    findings = [
        _make_finding(key="k.b", issue_category="style", rule_id="S1"),
        _make_finding(key="k.b", issue_category="style", rule_id="S2"),
    ]
    result = lt_findings_to_signal_dict(findings)

    sig = result["k.b"]
    assert sig["lt_style_flags"] == 2
    assert sig["lt_grammar_flags"] == 0
    assert sig["lt_literalness_support"] is True


# ---------------------------------------------------------------------------
# S5.  Unknown / other categories do not affect counters
# ---------------------------------------------------------------------------


def test_lt_findings_unknown_category_does_not_affect_counters() -> None:
    findings = [
        _make_finding(key="k.c", issue_category="typography", rule_id="T1"),
        _make_finding(key="k.c", issue_category="miscellaneous", rule_id="T2"),
    ]
    result = lt_findings_to_signal_dict(findings)

    sig = result["k.c"]
    assert sig["lt_grammar_flags"] == 0
    assert sig["lt_style_flags"] == 0
    assert sig["lt_literalness_support"] is False


# ---------------------------------------------------------------------------
# S6.  Rule IDs are deduplicated and capped at 5 per key
# ---------------------------------------------------------------------------


def test_lt_findings_rule_ids_dedup_and_cap() -> None:
    # 7 findings for the same key all with the same rule_id → deduplicated to 1
    findings = [_make_finding(key="k.d", rule_id="SAME") for _ in range(7)]
    result = lt_findings_to_signal_dict(findings)
    assert result["k.d"]["lt_rule_ids"] == ["SAME"]

    # 7 unique rule IDs → capped at 5
    findings2 = [_make_finding(key="k.e", rule_id=f"R{i}") for i in range(7)]
    result2 = lt_findings_to_signal_dict(findings2)
    assert len(result2["k.e"]["lt_rule_ids"]) == 5
    # First 5 encountered are kept
    assert result2["k.e"]["lt_rule_ids"] == ["R0", "R1", "R2", "R3", "R4"]


# ---------------------------------------------------------------------------
# S7.  Multiple keys are grouped independently
# ---------------------------------------------------------------------------


def test_lt_findings_multiple_keys_grouped_independently() -> None:
    findings = [
        _make_finding(key="k.x", issue_category="grammar", rule_id="G1"),
        _make_finding(key="k.x", issue_category="grammar", rule_id="G2"),
        _make_finding(key="k.y", issue_category="style", rule_id="S1"),
    ]
    result = lt_findings_to_signal_dict(findings)

    assert result["k.x"]["lt_grammar_flags"] == 2
    assert result["k.x"]["lt_style_flags"] == 0
    assert result["k.y"]["lt_grammar_flags"] == 0
    assert result["k.y"]["lt_style_flags"] == 1
    assert result["k.y"]["lt_literalness_support"] is True


# ---------------------------------------------------------------------------
# S8.  Custom session_mode is recorded in sources
# ---------------------------------------------------------------------------


def test_lt_findings_custom_session_mode_in_sources() -> None:
    finding = _make_finding(key="k.f")
    result = lt_findings_to_signal_dict([finding], session_mode="local_bundled_server")
    assert "local_bundled_server" in result["k.f"]["sources"]


# ---------------------------------------------------------------------------
# S9.  Default session_mode is "languagetool_layer"
# ---------------------------------------------------------------------------


def test_lt_findings_default_session_mode() -> None:
    finding = _make_finding(key="k.g")
    result = lt_findings_to_signal_dict([finding])
    assert result["k.g"]["sources"] == ["languagetool_layer"]


# ---------------------------------------------------------------------------
# S10. Output is compatible with merge_linguistic_signals
#      (this is the contract compatibility test — verifies the shapes are
#      identical enough that merge_linguistic_signals does not raise or produce
#      wrong types when fed output from lt_findings_to_signal_dict)
# ---------------------------------------------------------------------------


def test_lt_findings_to_signal_dict_compatible_with_merge_linguistic_signals() -> None:
    from l10n_audit.core.context_evaluator import merge_linguistic_signals

    # Produce signal dict from the layer bridge
    findings = [
        _make_finding(key="merge.key", issue_category="grammar", rule_id="G1"),
        _make_finding(key="merge.key", issue_category="style", rule_id="S1"),
    ]
    layer_signals = lt_findings_to_signal_dict(findings)

    # Produce a fake "other" signal dict (simulates what load_en_languagetool_signals returns)
    other_signals = {
        "merge.key": {
            "lt_style_flags": 1,
            "lt_grammar_flags": 0,
            "lt_literalness_support": True,
            "lt_rule_ids": ["OTHER_R1"],
            "sources": ["grammar_audit_report"],
        }
    }

    # merge_linguistic_signals must not raise and must produce correct types
    merged = merge_linguistic_signals(layer_signals, other_signals)

    assert "merge.key" in merged
    sig = merged["merge.key"]
    assert isinstance(sig["lt_grammar_flags"], int)
    assert isinstance(sig["lt_style_flags"], int)
    assert isinstance(sig["lt_literalness_support"], bool)
    assert isinstance(sig["lt_rule_ids"], list)
    assert isinstance(sig["sources"], list)

    # Counter values must be summed correctly
    assert sig["lt_grammar_flags"] == 1   # 1 from layer + 0 from other
    assert sig["lt_style_flags"] == 2     # 1 from layer + 1 from other
    # Both source labels must appear
    assert "languagetool_layer" in sig["sources"]
    assert "grammar_audit_report" in sig["sources"]

