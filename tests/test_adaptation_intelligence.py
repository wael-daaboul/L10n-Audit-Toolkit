"""
tests/test_adaptation_intelligence.py
=======================================
Phase 14 — Controlled Adaptive Intelligence Layer Tests.

Contract under test:
- Feature gate: disabled config returns None immediately
- Determinism: same LearningProfile + same config → identical report across 3 runs
- Safety: unknown signal_key rejected
- Safety: source_run_count < min_runs_required rejected
- Mode: shadow returns None
- Mode: suggest returns AdaptationReport
- Mode: prepare_bounded_actions returns report with bounded candidates
- No mutation of input LearningProfile
- No file I/O
- No behavior change to existing pipeline outputs
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from l10n_audit.core.adaptation_intelligence import (
    ALLOWED_SIGNAL_KEYS,
    AdaptationIntelligenceError,
    AdaptationProposal,
    AdaptationReport,
    _analyze_proposals,
    _apply_mode_gate,
    _build_proposal_id,
    _build_report,
    _hash_profile,
    _normalize_numeric,
    _resolve_thresholds,
    _validate_safety,
    compute_adaptation_report,
    load_adaptation_report,
    serialise_adaptation_report,
    write_adaptation_report,
)


# ---------------------------------------------------------------------------
# Minimal LearningProfile stub
# ---------------------------------------------------------------------------

@dataclass
class _Profile:
    project_id: str = "test_project"
    run_count: int = 10
    avg_total_issues: float = 15.0
    avg_auto_fix_rate: float = 0.05      # below auto_fix_rate_low threshold (0.10)
    avg_ai_review_rate: float = 0.90     # above ai_review_rate_high threshold (0.85)
    avg_manual_review_rate: float = 0.75 # above manual_review_rate_high threshold (0.70)
    avg_context_adjusted_rate: float = 0.50  # above context_adjustment_rate_high (0.40)
    dominant_category: str = "grammar"
    arabic_run_count: int = 9            # arabic_ratio = 0.9 > threshold (0.80)
    calibration_active_runs: int = 1     # cal_ratio = 0.1 < threshold (0.20)
    routing_enabled_runs: int = 5
    first_seen: float = 1000.0
    last_seen: float = 9000.0


def _default_config(mode: str = "suggest") -> dict:
    return {
        "enabled": True,
        "mode": mode,
        "min_runs_required": 5,
        "thresholds": {
            "manual_review_rate_high": 0.70,
            "ai_review_rate_high": 0.85,
            "auto_fix_rate_low": 0.10,
            "context_adjustment_rate_high": 0.40,
            "arabic_run_dominance": 0.80,
            "calibration_rarely_active": 0.20,
        },
    }


# ---------------------------------------------------------------------------
# Test 1 — Feature gate: disabled config returns None
# ---------------------------------------------------------------------------

def test_disabled_returns_none():
    profile = _Profile()
    config = {"enabled": False, "mode": "suggest"}
    assert compute_adaptation_report(profile, config) is None


def test_absent_enabled_returns_none():
    profile = _Profile()
    assert compute_adaptation_report(profile, {}) is None


def test_non_dict_config_returns_none():
    profile = _Profile()
    assert compute_adaptation_report(profile, "not_a_dict") is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test 2 — Determinism: same inputs → identical report across 3 independent calls
# ---------------------------------------------------------------------------

def test_determinism_three_runs():
    profile = _Profile()
    config = _default_config("suggest")

    reports = [compute_adaptation_report(profile, config) for _ in range(3)]

    assert all(r is not None for r in reports), "All 3 calls must return a report"

    ref = reports[0]
    for r in reports[1:]:
        assert r.project_id == ref.project_id
        assert r.mode == ref.mode
        assert r.profile_hash == ref.profile_hash
        assert r.run_count_basis == ref.run_count_basis
        assert len(r.proposals) == len(ref.proposals)
        for p_ref, p_r in zip(ref.proposals, r.proposals):
            assert p_ref.proposal_id == p_r.proposal_id
            assert p_ref.signal_key == p_r.signal_key
            assert p_ref.signal_value == p_r.signal_value
            assert p_ref.reasoning == p_r.reasoning


def test_adaptation_report_serialisation_is_deterministic():
    profile = _Profile()
    config = _default_config("suggest")

    report_a = compute_adaptation_report(profile, config)
    report_b = compute_adaptation_report(profile, config)

    assert report_a is not None
    assert report_b is not None
    assert serialise_adaptation_report(report_a) == serialise_adaptation_report(report_b)


def test_write_and_load_adaptation_report_round_trip(tmp_path):
    report = compute_adaptation_report(_Profile(), _default_config("prepare_bounded_actions"))
    assert report is not None

    path = tmp_path / "adaptation_report.json"
    write_adaptation_report(report, str(path))
    loaded = load_adaptation_report(str(path))

    assert serialise_adaptation_report(loaded) == serialise_adaptation_report(report)


def test_determinism_profile_hash_stable():
    """_hash_profile must produce identical output for the same field values."""
    p1 = _Profile()
    p2 = _Profile()
    assert _hash_profile(p1) == _hash_profile(p2)


def test_determinism_proposal_id_stable():
    """_build_proposal_id must be stable given the same inputs."""
    pid1 = _build_proposal_id("manual_review_rate_high", 0.75, "abc123")
    pid2 = _build_proposal_id("manual_review_rate_high", 0.75, "abc123")
    assert pid1 == pid2


def test_determinism_normalization():
    """_normalize_numeric rounds to 4dp for stable canonical hashing."""
    assert _normalize_numeric(0.123456789) == 0.1235
    assert _normalize_numeric(0.7) == 0.7
    assert _normalize_numeric(1.0) == 1.0


# ---------------------------------------------------------------------------
# Test 3 — Safety: unknown signal_key is rejected
# ---------------------------------------------------------------------------

def test_unknown_signal_key_rejected():
    profile = _Profile()
    profile_hash = _hash_profile(profile)
    bad_proposal = AdaptationProposal(
        proposal_id="abc123",
        signal_key="totally_unknown_signal",   # not in ALLOWED_SIGNAL_KEYS
        signal_value=0.9,
        threshold_used=0.5,
        proposal_type="observation",
        reasoning="some reason",
        source_run_count=10,
        profile_hash=profile_hash,
    )
    valid, rejections = _validate_safety([bad_proposal], min_runs=5)
    assert len(valid) == 0
    assert len(rejections) == 1
    assert "unknown_signal" in rejections[0]


def test_all_allowed_signal_keys_are_valid():
    """Every key in ALLOWED_SIGNAL_KEYS must pass the unknown_signal check."""
    profile = _Profile()
    profile_hash = _hash_profile(profile)
    for key in ALLOWED_SIGNAL_KEYS:
        p = AdaptationProposal(
            proposal_id="x",
            signal_key=key,
            signal_value=0.5,
            threshold_used=0.5,
            proposal_type="observation",
            reasoning="non-empty reason",
            source_run_count=10,
            profile_hash=profile_hash,
        )
        valid, rejections = _validate_safety([p], min_runs=5)
        assert len(valid) == 1, f"Key {key!r} should be valid but was rejected: {rejections}"


# ---------------------------------------------------------------------------
# Test 4 — Safety: source_run_count < min_runs_required rejected
# ---------------------------------------------------------------------------

def test_insufficient_runs_rejected():
    profile = _Profile()
    profile_hash = _hash_profile(profile)
    low_run_proposal = AdaptationProposal(
        proposal_id="abc",
        signal_key="manual_review_rate_high",
        signal_value=0.75,
        threshold_used=0.70,
        proposal_type="recommendation",
        reasoning="manual review rate is high",
        source_run_count=3,   # below min_runs=5
        profile_hash=profile_hash,
    )
    valid, rejections = _validate_safety([low_run_proposal], min_runs=5)
    assert len(valid) == 0
    assert len(rejections) == 1
    assert "insufficient_runs" in rejections[0]


def test_exactly_min_runs_is_accepted():
    profile = _Profile()
    profile_hash = _hash_profile(profile)
    p = AdaptationProposal(
        proposal_id="abc",
        signal_key="manual_review_rate_high",
        signal_value=0.75,
        threshold_used=0.70,
        proposal_type="recommendation",
        reasoning="manual review rate is high",
        source_run_count=5,   # exactly min_runs — must pass
        profile_hash=profile_hash,
    )
    valid, rejections = _validate_safety([p], min_runs=5)
    assert len(valid) == 1
    assert len(rejections) == 0


# ---------------------------------------------------------------------------
# Test 5 — Mode: shadow returns None
# ---------------------------------------------------------------------------

def test_shadow_mode_returns_none():
    profile = _Profile()
    config = _default_config("shadow")
    result = compute_adaptation_report(profile, config)
    assert result is None


def test_apply_mode_gate_shadow_returns_none():
    proposals = [
        AdaptationProposal(
            proposal_id="x", signal_key="manual_review_rate_high",
            signal_value=0.75, threshold_used=0.70,
            proposal_type="recommendation", reasoning="r",
            source_run_count=10, profile_hash="abc",
        )
    ]
    assert _apply_mode_gate(proposals, "shadow") is None


# ---------------------------------------------------------------------------
# Test 6 — Mode: suggest returns AdaptationReport
# ---------------------------------------------------------------------------

def test_suggest_mode_returns_report():
    profile = _Profile()
    config = _default_config("suggest")
    result = compute_adaptation_report(profile, config)
    assert isinstance(result, AdaptationReport)
    assert result.mode == "suggest"
    assert result.project_id == "test_project"
    assert result.run_count_basis == 10
    assert len(result.proposals) > 0


def test_suggest_mode_proposals_have_required_fields():
    profile = _Profile()
    config = _default_config("suggest")
    result = compute_adaptation_report(profile, config)
    assert result is not None
    for p in result.proposals:
        assert p.proposal_id, "proposal_id must be non-empty"
        assert p.signal_key in ALLOWED_SIGNAL_KEYS
        assert isinstance(p.signal_value, float)
        assert isinstance(p.threshold_used, float)
        assert p.proposal_type in {"observation", "recommendation", "bounded_action_candidate"}
        assert p.reasoning.strip(), "reasoning must be non-empty"
        assert p.source_run_count >= 5
        assert p.profile_hash, "profile_hash must be non-empty"


# ---------------------------------------------------------------------------
# Test 7 — Mode: prepare_bounded_actions
# ---------------------------------------------------------------------------

def test_prepare_bounded_actions_returns_report():
    profile = _Profile()
    config = _default_config("prepare_bounded_actions")
    result = compute_adaptation_report(profile, config)
    assert isinstance(result, AdaptationReport)
    assert result.mode == "prepare_bounded_actions"


def test_prepare_bounded_actions_marks_recommendations():
    profile = _Profile()
    config = _default_config("prepare_bounded_actions")
    result = compute_adaptation_report(profile, config)
    assert result is not None

    bounded = [p for p in result.proposals if p.proposal_type == "bounded_action_candidate"]
    # Our profile triggers manual_review_rate_high and calibration_rarely_active
    # as recommendations — those should become bounded_action_candidates.
    assert len(bounded) > 0, "At least one bounded_action_candidate expected"
    for p in bounded:
        assert p.bounded_action_key is not None
        assert p.bounded_action_key.startswith("phase14::")


def test_prepare_bounded_actions_observations_unchanged():
    """Observation-type proposals must not become bounded_action_candidates."""
    profile = _Profile()
    config = _default_config("prepare_bounded_actions")
    result = compute_adaptation_report(profile, config)
    assert result is not None

    for p in result.proposals:
        if p.proposal_type == "observation":
            assert p.bounded_action_key is None, (
                f"Observation {p.signal_key!r} must not have a bounded_action_key"
            )


def test_load_adaptation_report_corrupt_json_fails_loudly(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{bad json", encoding="utf-8")

    with pytest.raises(AdaptationIntelligenceError, match="Corrupt adaptation report JSON"):
        load_adaptation_report(str(path))


# ---------------------------------------------------------------------------
# Test 8 — No mutation of input LearningProfile
# ---------------------------------------------------------------------------

def test_no_mutation_of_input_profile():
    profile = _Profile()
    original_run_count = profile.run_count
    original_avg_auto_fix = profile.avg_auto_fix_rate
    original_dominant = profile.dominant_category

    config = _default_config("suggest")
    compute_adaptation_report(profile, config)

    assert profile.run_count == original_run_count
    assert profile.avg_auto_fix_rate == original_avg_auto_fix
    assert profile.dominant_category == original_dominant


def test_no_mutation_of_input_config():
    profile = _Profile()
    config = _default_config("suggest")
    config_before = copy.deepcopy(config)

    compute_adaptation_report(profile, config)

    assert config == config_before, "config dict must not be mutated by compute_adaptation_report"


# ---------------------------------------------------------------------------
# Test 9 — No file I/O
# ---------------------------------------------------------------------------

def test_no_file_io(tmp_path, monkeypatch):
    """compute_adaptation_report must not open any files."""
    opened_files = []
    real_open = open

    def _tracking_open(file, *args, **kwargs):
        opened_files.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _tracking_open)

    profile = _Profile()
    config = _default_config("suggest")
    compute_adaptation_report(profile, config)

    assert opened_files == [], (
        f"compute_adaptation_report must not open any files; opened: {opened_files}"
    )


# ---------------------------------------------------------------------------
# Test 10 — No behavior changes to existing outputs / backward compatibility
# ---------------------------------------------------------------------------

def test_module_not_imported_by_decision_engine():
    """adaptation_intelligence must not be imported by decision_engine."""
    import l10n_audit.core.decision_engine as de
    # If adaptation_intelligence is in the module's globals, it was imported at top level.
    assert "adaptation_intelligence" not in dir(de)


def test_module_not_imported_by_calibration_engine():
    import l10n_audit.core.calibration_engine as ce
    assert "adaptation_intelligence" not in dir(ce)


def test_module_not_imported_by_context_profile():
    import l10n_audit.core.context_profile as cp
    assert "adaptation_intelligence" not in dir(cp)


def test_disabled_gate_is_truly_zero_cost(monkeypatch):
    """When disabled, _analyze_proposals must never be called."""
    called = []

    def _fake_analyze(*args, **kwargs):
        called.append(True)
        return []

    monkeypatch.setattr(
        "l10n_audit.core.adaptation_intelligence._analyze_proposals",
        _fake_analyze,
    )

    profile = _Profile()
    result = compute_adaptation_report(profile, {"enabled": False})
    assert result is None
    assert called == [], "_analyze_proposals must not be called when disabled"


# ---------------------------------------------------------------------------
# Test 11 — Threshold resolution
# ---------------------------------------------------------------------------

def test_resolve_thresholds_uses_defaults_when_config_empty():
    from l10n_audit.core.adaptation_intelligence import _DEFAULT_THRESHOLDS
    result = _resolve_thresholds({})
    assert result == _DEFAULT_THRESHOLDS


def test_resolve_thresholds_override_applies():
    result = _resolve_thresholds({"thresholds": {"manual_review_rate_high": 0.50}})
    assert result["manual_review_rate_high"] == 0.50
    # Other keys must retain their defaults
    assert result["ai_review_rate_high"] == 0.85


def test_resolve_thresholds_unknown_keys_ignored():
    result = _resolve_thresholds({"thresholds": {"totally_made_up_key": 0.99}})
    # Unknown key must not appear in result
    assert "totally_made_up_key" not in result


def test_resolve_thresholds_invalid_value_falls_back():
    result = _resolve_thresholds({"thresholds": {"manual_review_rate_high": "not_a_float"}})
    from l10n_audit.core.adaptation_intelligence import _DEFAULT_THRESHOLDS
    assert result["manual_review_rate_high"] == _DEFAULT_THRESHOLDS["manual_review_rate_high"]


# ---------------------------------------------------------------------------
# Test 12 — Edge case: empty or minimal profile
# ---------------------------------------------------------------------------

def test_zero_run_count_returns_none_or_no_proposals():
    """A profile with run_count=0 should produce no valid proposals (all fail min_runs check)."""
    profile = _Profile()
    profile.run_count = 0
    profile.arabic_run_count = 0
    profile.calibration_active_runs = 0

    config = _default_config("suggest")
    result = compute_adaptation_report(profile, config)
    # May return None (no valid proposals) or an empty report
    if result is not None:
        assert len(result.proposals) == 0


def test_profile_with_all_rates_in_range_produces_fewer_proposals():
    """A well-performing profile that meets all thresholds should trigger fewer signals."""
    profile = _Profile()
    profile.avg_manual_review_rate = 0.30   # below 0.70 — no signal
    profile.avg_ai_review_rate = 0.60       # below 0.85 — no signal
    profile.avg_auto_fix_rate = 0.40        # above 0.10 — no signal
    profile.avg_context_adjusted_rate = 0.10  # below 0.40 — no signal
    profile.arabic_run_count = 1            # ratio 0.1 < 0.80 — no signal
    profile.calibration_active_runs = 8     # ratio 0.8 > 0.20 — no signal

    config = _default_config("suggest")
    result = compute_adaptation_report(profile, config)
    assert result is not None
    # All rate signals should be absent for a healthy profile
    rate_signals = {
        "manual_review_rate_high", "ai_review_rate_high", "auto_fix_rate_low",
        "context_adjustment_rate_high", "arabic_run_dominance", "calibration_rarely_active",
    }
    fired_keys = {p.signal_key for p in result.proposals}
    assert fired_keys.isdisjoint(rate_signals), (
        f"No rate signals should fire for a healthy profile; fired: {fired_keys & rate_signals}"
    )


# ---------------------------------------------------------------------------
# Test 13 — Proposals are sorted deterministically
# ---------------------------------------------------------------------------

def test_proposals_sorted_by_signal_key():
    profile = _Profile()
    config = _default_config("suggest")
    result = compute_adaptation_report(profile, config)
    assert result is not None
    keys = [p.signal_key for p in result.proposals]
    assert keys == sorted(keys), f"Proposals must be sorted by signal_key; got {keys}"


# ---------------------------------------------------------------------------
# Test 14 — Safety rejection collection
# ---------------------------------------------------------------------------

def test_safety_rejections_are_collected_in_report():
    """Invalid proposals must appear in safety_rejections, not proposals."""
    profile_hash = _hash_profile(_Profile())
    candidates = [
        AdaptationProposal(
            proposal_id="good",
            signal_key="manual_review_rate_high",
            signal_value=0.75,
            threshold_used=0.70,
            proposal_type="recommendation",
            reasoning="high rate",
            source_run_count=10,
            profile_hash=profile_hash,
        ),
        AdaptationProposal(
            proposal_id="bad",
            signal_key="not_allowed_key",   # will be rejected
            signal_value=0.9,
            threshold_used=0.5,
            proposal_type="observation",
            reasoning="some text",
            source_run_count=10,
            profile_hash=profile_hash,
        ),
    ]
    valid, rejections = _validate_safety(candidates, min_runs=5)
    assert len(valid) == 1
    assert len(rejections) == 1
    assert valid[0].signal_key == "manual_review_rate_high"
