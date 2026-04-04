"""
tests/test_controlled_consumption.py
======================================
Phase 15 — Controlled Consumption Layer Tests.

Contract under test:
- Feature gate: disabled config returns None immediately
- Double opt-in: empty allowlists produce zero actions (but a valid manifest)
- Governance rules: each rule fires and produces a deterministic rejection reason
- Static mapping: calibration_rarely_active -> calibration.enabled = True
- manual_review_rate_high produces no action in v1
- Forbidden targets are always blocked
- approved_by_default is always False
- shadow mode returns None
- generate_manifest returns ConsumptionManifest (metadata-safe)
- review_ready writes an atomic .cache file
- Determinism: same inputs -> same manifest across 3 runs
- No mutation of input AdaptationReport
- No behavior changes to existing pipeline outputs
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from typing import Any, List, Optional

import pytest

from l10n_audit.core.controlled_consumption import (
    SIGNAL_TO_ACTION_MAP,
    ConsumableAction,
    ConsumptionManifest,
    _apply_governance_rules,
    _build_action_id,
    _build_manifest_id,
    _generate_actions,
    _get_current_value,
    _hash_report,
    _is_forbidden_target,
    generate_consumption_manifest,
)


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

@dataclass
class _Proposal:
    proposal_id: str = "prop_abc123"
    signal_key: str = "calibration_rarely_active"
    signal_value: float = 0.10
    threshold_used: float = 0.20
    proposal_type: str = "bounded_action_candidate"
    reasoning: str = "Calibration was active in only 1/10 runs."
    source_run_count: int = 10
    profile_hash: str = "deadbeef01234567"
    bounded_action_key: Optional[str] = "phase14::calibration_rarely_active"


@dataclass
class _Report:
    project_id: str = "test_project"
    mode: str = "prepare_bounded_actions"
    run_count_basis: int = 10
    profile_hash: str = "deadbeef01234567"
    proposals: List[Any] = field(default_factory=list)
    safety_rejections: List[str] = field(default_factory=list)


def _default_config(mode: str = "generate_manifest") -> dict:
    return {
        "enabled": True,
        "mode": mode,
        "min_runs_required": 5,
        "emit_manifest": False,
        "allowed_signal_keys": ["calibration_rarely_active"],
        "allowed_action_types": ["config_suggestion"],
    }


def _current_config() -> dict:
    return {
        "calibration": {
            "enabled": False,
            "mode": "shadow",
        }
    }


def _eligible_report() -> _Report:
    return _Report(proposals=[_Proposal()])


# ---------------------------------------------------------------------------
# Test 1 — Feature gate: disabled config returns None
# ---------------------------------------------------------------------------

def test_disabled_config_returns_none():
    report = _eligible_report()
    result = generate_consumption_manifest(report, {"enabled": False}, _current_config())
    assert result is None


def test_absent_enabled_key_returns_none():
    report = _eligible_report()
    result = generate_consumption_manifest(report, {}, _current_config())
    assert result is None


def test_non_dict_config_returns_none():
    report = _eligible_report()
    result = generate_consumption_manifest(report, "not_a_dict", _current_config())  # type: ignore[arg-type]
    assert result is None


# ---------------------------------------------------------------------------
# Test 2 — Empty allowlists produce an empty manifest, not None
# ---------------------------------------------------------------------------

def test_empty_allowed_signal_keys_produces_empty_manifest():
    report = _eligible_report()
    config = _default_config()
    config["allowed_signal_keys"] = []
    result = generate_consumption_manifest(report, config, _current_config())
    assert isinstance(result, ConsumptionManifest)
    assert len(result.generated_actions) == 0


def test_empty_allowed_action_types_produces_empty_manifest():
    report = _eligible_report()
    config = _default_config()
    config["allowed_action_types"] = []
    result = generate_consumption_manifest(report, config, _current_config())
    assert isinstance(result, ConsumptionManifest)
    assert len(result.generated_actions) == 0


def test_both_allowlists_empty_produces_empty_manifest():
    report = _eligible_report()
    config = _default_config()
    config["allowed_signal_keys"] = []
    config["allowed_action_types"] = []
    result = generate_consumption_manifest(report, config, _current_config())
    assert isinstance(result, ConsumptionManifest)
    assert len(result.generated_actions) == 0


# ---------------------------------------------------------------------------
# Test 3 — Unknown signal is rejected (G3)
# ---------------------------------------------------------------------------

def test_unknown_signal_rejected_by_G3():
    proposal = _Proposal(signal_key="not_in_static_map", bounded_action_key="phase14::not_in_static_map")
    config = _default_config()
    config["allowed_signal_keys"] = ["not_in_static_map"]

    action, reason = _apply_governance_rules(proposal, config, _current_config())
    assert action is None
    assert reason is not None
    assert "G3_REJECTED" in reason
    assert "no_static_mapping" in reason


# ---------------------------------------------------------------------------
# Test 4 — Non-bounded_action_candidate proposal is rejected (G1)
# ---------------------------------------------------------------------------

def test_observation_proposal_rejected_by_G1():
    proposal = _Proposal(proposal_type="observation")
    config = _default_config()

    action, reason = _apply_governance_rules(proposal, config, _current_config())
    assert action is None
    assert reason is not None
    assert "G1_REJECTED" in reason
    assert "wrong_proposal_type" in reason


def test_recommendation_proposal_rejected_by_G1():
    proposal = _Proposal(proposal_type="recommendation")
    config = _default_config()

    action, reason = _apply_governance_rules(proposal, config, _current_config())
    assert action is None
    assert reason is not None
    assert "G1_REJECTED" in reason


# ---------------------------------------------------------------------------
# Test 5 — calibration_rarely_active maps correctly to calibration.enabled = True
# ---------------------------------------------------------------------------

def test_calibration_rarely_active_maps_to_calibration_enabled():
    proposal = _Proposal()
    config = _default_config()

    action, reason = _apply_governance_rules(proposal, config, _current_config())
    assert action is not None, f"Unexpected rejection: {reason}"
    assert reason is None
    assert action.signal_key == "calibration_rarely_active"
    assert action.action_type == "config_suggestion"
    assert action.target_config_key == "calibration.enabled"
    assert action.suggested_value is True
    assert action.rollback_key == "calibration.enabled"


def test_calibration_rarely_active_captures_current_value():
    proposal = _Proposal()
    config = _default_config()
    current = {"calibration": {"enabled": False}}

    action, _ = _apply_governance_rules(proposal, config, current)
    assert action is not None
    assert action.current_value is False   # captured from current config


def test_calibration_rarely_active_current_value_none_when_absent():
    proposal = _Proposal()
    config = _default_config()
    current = {}  # key doesn't exist yet

    action, _ = _apply_governance_rules(proposal, config, current)
    assert action is not None
    assert action.current_value is None    # key absent → None is correct


# ---------------------------------------------------------------------------
# Test 6 — manual_review_rate_high does NOT map to anything in v1
# ---------------------------------------------------------------------------

def test_manual_review_rate_high_has_no_static_mapping():
    assert "manual_review_rate_high" not in SIGNAL_TO_ACTION_MAP


def test_manual_review_rate_high_rejected_by_governance():
    proposal = _Proposal(
        signal_key="manual_review_rate_high",
        bounded_action_key="phase14::manual_review_rate_high",
    )
    config = _default_config()
    config["allowed_signal_keys"] = ["manual_review_rate_high"]

    action, reason = _apply_governance_rules(proposal, config, _current_config())
    assert action is None
    assert reason is not None
    assert "G3_REJECTED" in reason


# ---------------------------------------------------------------------------
# Test 7 — Forbidden target keys are blocked (G5)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_key", [
    "decision_engine.something",
    "routing.table",
    "calibration.mode",
    "calibration.max_adjustment",
    "calibration.thresholds.auto_fix",
    "context_profile.risk_tolerance",
    "arabic.routing",
    "conflict.priority",
    "enforcement.layer",
    "output.results_dir",
    "report.format",
    "review_queue.path",
    "score_finding.weights",
])
def test_forbidden_target_is_always_blocked(bad_key):
    assert _is_forbidden_target(bad_key), f"Expected {bad_key!r} to be forbidden"


def test_calibration_enabled_is_not_forbidden():
    assert not _is_forbidden_target("calibration.enabled")


# ---------------------------------------------------------------------------
# Test 8 — approved_by_default is always False
# ---------------------------------------------------------------------------

def test_approved_by_default_is_always_false():
    proposal = _Proposal()
    config = _default_config()
    action, _ = _apply_governance_rules(proposal, config, _current_config())
    assert action is not None
    assert action.approved_by_default is False


def test_approved_by_default_in_full_manifest():
    report = _eligible_report()
    config = _default_config()
    result = generate_consumption_manifest(report, config, _current_config())
    assert result is not None
    for action in result.generated_actions:
        assert action.approved_by_default is False, (
            f"action {action.action_id!r} has approved_by_default=True — must always be False"
        )


# ---------------------------------------------------------------------------
# Test 9 — shadow mode returns None
# ---------------------------------------------------------------------------

def test_shadow_mode_returns_none():
    report = _eligible_report()
    config = _default_config("shadow")
    result = generate_consumption_manifest(report, config, _current_config())
    assert result is None


def test_shadow_mode_writes_no_files(tmp_path):
    report = _eligible_report()
    config = _default_config("shadow")
    config["emit_manifest"] = True  # should be irrelevant in shadow
    generate_consumption_manifest(report, config, _current_config(), str(tmp_path))
    assert not any(tmp_path.iterdir()), "shadow mode must not write any files"


# ---------------------------------------------------------------------------
# Test 10 — generate_manifest returns a metadata-safe ConsumptionManifest
# ---------------------------------------------------------------------------

def test_generate_manifest_returns_manifest():
    report = _eligible_report()
    config = _default_config("generate_manifest")
    result = generate_consumption_manifest(report, config, _current_config())
    assert isinstance(result, ConsumptionManifest)
    assert result.mode == "generate_manifest"
    assert result.project_id == "test_project"
    assert result.schema_version == "1.0"


def test_generate_manifest_does_not_write_files(tmp_path):
    report = _eligible_report()
    config = _default_config("generate_manifest")
    config["emit_manifest"] = False
    generate_consumption_manifest(report, config, _current_config(), str(tmp_path))
    cache_dir = tmp_path / ".cache" / "consumption_manifests"
    assert not cache_dir.exists(), "generate_manifest must not write files when emit_manifest=False"


def test_generate_manifest_has_one_action_for_eligible_proposal():
    report = _eligible_report()
    config = _default_config("generate_manifest")
    result = generate_consumption_manifest(report, config, _current_config())
    assert result is not None
    assert len(result.generated_actions) == 1
    action = result.generated_actions[0]
    assert action.target_config_key == "calibration.enabled"
    assert action.suggested_value is True
    assert action.safety_checks_passed is True


# ---------------------------------------------------------------------------
# Test 11 — review_ready writes an isolated .cache file atomically
# ---------------------------------------------------------------------------

def test_review_ready_writes_cache_file(tmp_path):
    report = _eligible_report()
    config = _default_config("review_ready")
    config["emit_manifest"] = True
    result = generate_consumption_manifest(report, config, _current_config(), str(tmp_path))

    assert result is not None
    cache_dir = tmp_path / ".cache" / "consumption_manifests"
    assert cache_dir.is_dir()
    files = list(cache_dir.glob("*.json"))
    assert len(files) == 1, f"Expected 1 JSON file; found {files}"


def test_review_ready_no_tmp_files_left(tmp_path):
    report = _eligible_report()
    config = _default_config("review_ready")
    config["emit_manifest"] = True
    generate_consumption_manifest(report, config, _current_config(), str(tmp_path))

    cache_dir = tmp_path / ".cache" / "consumption_manifests"
    tmp_files = list(cache_dir.glob("*.tmp")) if cache_dir.exists() else []
    assert tmp_files == [], f"Leftover .tmp files: {tmp_files}"


def test_review_ready_file_is_valid_json(tmp_path):
    report = _eligible_report()
    config = _default_config("review_ready")
    config["emit_manifest"] = True
    result = generate_consumption_manifest(report, config, _current_config(), str(tmp_path))

    assert result is not None
    cache_dir = tmp_path / ".cache" / "consumption_manifests"
    json_file = next(cache_dir.glob("*.json"))
    with open(json_file, encoding="utf-8") as fh:
        data = json.load(fh)

    assert data["project_id"] == "test_project"
    assert data["schema_version"] == "1.0"
    assert data["mode"] == "review_ready"
    assert isinstance(data["generated_actions"], list)


def test_review_ready_emit_false_writes_no_file(tmp_path):
    report = _eligible_report()
    config = _default_config("review_ready")
    config["emit_manifest"] = False   # explicitly off
    generate_consumption_manifest(report, config, _current_config(), str(tmp_path))
    cache_dir = tmp_path / ".cache" / "consumption_manifests"
    assert not cache_dir.exists()


# ---------------------------------------------------------------------------
# Test 12 — Determinism across 3 repeated calls
# ---------------------------------------------------------------------------

def test_determinism_three_runs():
    report = _eligible_report()
    config = _default_config("generate_manifest")
    current = _current_config()

    results = [generate_consumption_manifest(report, config, current) for _ in range(3)]
    assert all(r is not None for r in results)

    ref = results[0]
    for r in results[1:]:
        assert r.manifest_id == ref.manifest_id
        assert r.source_report_hash == ref.source_report_hash
        assert len(r.generated_actions) == len(ref.generated_actions)
        for a_ref, a in zip(ref.generated_actions, r.generated_actions):
            assert a.action_id == a_ref.action_id
            assert a.target_config_key == a_ref.target_config_key
            assert a.suggested_value == a_ref.suggested_value


def test_determinism_hash_report_stable():
    report = _eligible_report()
    h1 = _hash_report(report)
    h2 = _hash_report(report)
    assert h1 == h2


def test_determinism_action_id_stable():
    aid1 = _build_action_id("prop_abc", "config_suggestion", "calibration.enabled", True)
    aid2 = _build_action_id("prop_abc", "config_suggestion", "calibration.enabled", True)
    assert aid1 == aid2


def test_determinism_manifest_id_stable():
    report = _eligible_report()
    config = _default_config("generate_manifest")
    r1 = generate_consumption_manifest(report, config, _current_config())
    r2 = generate_consumption_manifest(report, config, _current_config())
    assert r1 is not None and r2 is not None
    assert r1.manifest_id == r2.manifest_id


# ---------------------------------------------------------------------------
# Test 13 — No mutation of input AdaptationReport
# ---------------------------------------------------------------------------

def test_no_mutation_of_input_report():
    report = _eligible_report()
    original_proposals_len = len(report.proposals)
    original_project_id = report.project_id

    config = _default_config()
    generate_consumption_manifest(report, config, _current_config())

    assert len(report.proposals) == original_proposals_len
    assert report.project_id == original_project_id


def test_no_mutation_of_input_config():
    report = _eligible_report()
    config = _default_config()
    config_before = copy.deepcopy(config)

    generate_consumption_manifest(report, config, _current_config())

    assert config == config_before


def test_no_mutation_of_current_config():
    report = _eligible_report()
    config = _default_config()
    current = _current_config()
    current_before = copy.deepcopy(current)

    generate_consumption_manifest(report, config, current)

    assert current == current_before


# ---------------------------------------------------------------------------
# Test 14 — No behavior changes to existing outputs / isolation verification
# ---------------------------------------------------------------------------

def test_module_not_imported_by_decision_engine():
    import l10n_audit.core.decision_engine as de
    assert "controlled_consumption" not in dir(de)


def test_module_not_imported_by_calibration_engine():
    import l10n_audit.core.calibration_engine as ce
    assert "controlled_consumption" not in dir(ce)


def test_module_not_imported_by_adaptation_intelligence():
    import l10n_audit.core.adaptation_intelligence as ai
    assert "controlled_consumption" not in dir(ai)


def test_module_not_imported_by_project_memory():
    import l10n_audit.core.project_memory as pm
    assert "controlled_consumption" not in dir(pm)


def test_disabled_gate_calls_no_internals(monkeypatch):
    called = []

    def _fake_generate(*args, **kwargs):
        called.append(True)
        return []

    monkeypatch.setattr(
        "l10n_audit.core.controlled_consumption._generate_actions",
        _fake_generate,
    )

    report = _eligible_report()
    result = generate_consumption_manifest(report, {"enabled": False}, _current_config())
    assert result is None
    assert called == [], "_generate_actions must not be called when feature is disabled"


# ---------------------------------------------------------------------------
# Test 15 — Governance rejection completeness per rule
# ---------------------------------------------------------------------------

def test_G2_signal_not_in_allowlist():
    proposal = _Proposal()
    config = _default_config()
    config["allowed_signal_keys"] = []  # explicit empty

    action, reason = _apply_governance_rules(proposal, config, _current_config())
    assert action is None
    assert "G2_REJECTED" in (reason or "")


def test_G4_action_type_not_in_allowlist():
    proposal = _Proposal()
    config = _default_config()
    config["allowed_action_types"] = []  # explicit empty

    action, reason = _apply_governance_rules(proposal, config, _current_config())
    assert action is None
    assert "G4_REJECTED" in (reason or "")


def test_G6_insufficient_runs():
    proposal = _Proposal(source_run_count=2)
    config = _default_config()

    action, reason = _apply_governance_rules(proposal, config, _current_config())
    assert action is None
    assert "G6_REJECTED" in (reason or "")


def test_G7_empty_reasoning():
    proposal = _Proposal(reasoning="")
    config = _default_config()

    action, reason = _apply_governance_rules(proposal, config, _current_config())
    assert action is None
    assert "G7_REJECTED" in (reason or "")


# ---------------------------------------------------------------------------
# Test 16 — _get_current_value resolves dotted paths correctly
# ---------------------------------------------------------------------------

def test_get_current_value_nested_key():
    current = {"calibration": {"enabled": False, "mode": "shadow"}}
    assert _get_current_value("calibration.enabled", current) is False
    assert _get_current_value("calibration.mode", current) == "shadow"


def test_get_current_value_missing_key_returns_none():
    assert _get_current_value("calibration.enabled", {}) is None
    assert _get_current_value("nonexistent.key", {"other": 1}) is None


# ---------------------------------------------------------------------------
# Test 17 — source_report_hash and source_profile_hash are populated
# ---------------------------------------------------------------------------

def test_manifest_contains_source_hashes():
    report = _eligible_report()
    config = _default_config("generate_manifest")
    result = generate_consumption_manifest(report, config, _current_config())
    assert result is not None
    assert result.source_profile_hash == report.profile_hash
    assert len(result.source_report_hash) == 16   # sha256[:16]


# ---------------------------------------------------------------------------
# Test 18 — Static mapping sanity checks
# ---------------------------------------------------------------------------

def test_signal_to_action_map_has_exactly_one_entry():
    assert len(SIGNAL_TO_ACTION_MAP) == 1


def test_signal_to_action_map_entry_is_correct():
    entry = SIGNAL_TO_ACTION_MAP["calibration_rarely_active"]
    assert entry["action_type"] == "config_suggestion"
    assert entry["target_config_key"] == "calibration.enabled"
    assert entry["suggested_value"] is True


def test_signal_to_action_map_calibration_mode_absent():
    """calibration.mode must never appear as a suggested target in v1."""
    for signal, mapping in SIGNAL_TO_ACTION_MAP.items():
        assert mapping.get("target_config_key") != "calibration.mode", (
            f"Signal {signal!r} maps to calibration.mode — forbidden in v1"
        )
