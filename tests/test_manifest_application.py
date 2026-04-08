"""
tests/test_manifest_application.py
=====================================
Phase 16 — Human-Approved Manifest Application Layer Tests.

Contract under test:
1.  corrupt/missing manifest raises explicit ManifestApplicationError
2.  reviewed manifest built without mutating original ConsumptionManifest
3.  per-action approval works (approved / rejected / pending states)
4.  only "approved" actions are applied to the config
5.  "pending" and "rejected" actions are skipped (recorded in receipt.skipped_actions)
6.  unsupported action_type raises ManifestApplicationError
7.  forbidden target is re-checked independently and blocked
8.  receipt artifact persisted BEFORE config file is replaced
9.  config writes are atomic (.tmp + os.replace pattern)
10. rollback restores previous_value captured from live config
11. deterministic reviewed_manifest_id and receipt_id
12. no mutation of original input manifest dict
13. no dependency on engine.py or runtime pipeline
14. no changes to existing outputs/tests
"""
from __future__ import annotations

import json
import os
import copy
import pytest

from l10n_audit.core.manifest_application import (
    ManifestApplicationError,
    ApprovedAction,
    ReviewedManifest,
    RollbackRecord,
    ApplicationReceipt,
    _hash_content,
    _hash_config,
    _build_reviewed_manifest_id,
    _build_receipt_id,
    _recheck_forbidden_target,
    _resolve_dotted_key,
    _get_dotted_value,
    _set_dotted_key,
    _validate_manifest_integrity,
    _validate_approved_action,
    _apply_single_action,
    load_manifest,
    load_approvals_file,
    generate_reviewed_manifest,
    apply_manifest,
    rollback_application,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCHEMA_VERSION = "1.0"


def _make_manifest_file(tmp_path, manifest_id="mfst001", project_id="proj_test",
                        actions=None) -> str:
    """Write a minimal ConsumptionManifest JSON to disk. Returns path."""
    if actions is None:
        actions = [_default_action_dict()]
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "manifest_id": manifest_id,
        "project_id": project_id,
        "mode": "review_ready",
        "source_profile_hash": "deadbeef01234567",
        "source_report_hash": "abcd1234abcd1234",
        "generated_actions": actions,
        "rejected_candidates": [],
        "governance_rejections": [],
    }
    path = str(tmp_path / f"{project_id}_{manifest_id}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return path


def _default_action_dict(**overrides) -> dict:
    base = {
        "action_id": "act_000000000001",
        "proposal_id": "prop_abc123",
        "action_type": "config_suggestion",
        "target_config_key": "calibration.enabled",
        "current_value": False,
        "suggested_value": True,
        "rollback_key": "calibration.enabled",
        "justification": "Calibration was active in only 1/10 runs.",
        "safety_checks_passed": True,
        "approved_by_default": False,
    }
    base.update(overrides)
    return base


def _make_reviewed_manifest_file(tmp_path, source_manifest_id="mfst001",
                                  project_id="proj_test",
                                  reviewed_manifest_id=None,
                                  actions=None) -> str:
    if actions is None:
        actions = [
            {
                "action_id": "act_000000000001",
                "proposal_id": "prop_abc123",
                "action_type": "config_suggestion",
                "target_config_key": "calibration.enabled",
                "current_value": False,
                "approved_value": True,
                "approval_status": "approved",
                "rollback_key": "calibration.enabled",
                "approved_by": "tester",
                "approval_note": "",
            }
        ]
    if reviewed_manifest_id is None:
        reviewed_manifest_id = "rev000000001"
    payload = {
        "reviewed_manifest_id": reviewed_manifest_id,
        "schema_version": _SCHEMA_VERSION,
        "source_manifest_id": source_manifest_id,
        "project_id": project_id,
        "approved_actions": actions,
    }
    path = str(tmp_path / f"{project_id}_{reviewed_manifest_id}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return path


def _make_config_file(tmp_path, content=None) -> str:
    if content is None:
        content = {"calibration": {"enabled": False, "mode": "shadow"}}
    path = str(tmp_path / "config.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(content, fh, indent=2)
    return path


def _make_approved_action(**overrides) -> ApprovedAction:
    kwargs = dict(
        action_id="act_000000000001",
        proposal_id="prop_abc123",
        action_type="config_suggestion",
        target_config_key="calibration.enabled",
        current_value=False,
        approved_value=True,
        approval_status="approved",
        rollback_key="calibration.enabled",
        approved_by="tester",
        approval_note="",
    )
    kwargs.update(overrides)
    return ApprovedAction(**kwargs)


# ---------------------------------------------------------------------------
# Test 1 — Corrupt / missing manifest raises ManifestApplicationError
# ---------------------------------------------------------------------------

def test_load_manifest_missing_file_raises(tmp_path):
    with pytest.raises(ManifestApplicationError, match="File not found"):
        load_manifest(str(tmp_path / "nonexistent.json"))


def test_load_manifest_corrupt_json_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ManifestApplicationError, match="Corrupt JSON"):
        load_manifest(str(bad))


def test_load_manifest_wrong_schema_raises(tmp_path):
    payload = {
        "schema_version": "99.0",
        "manifest_id": "x",
        "project_id": "p",
        "generated_actions": [],
    }
    path = tmp_path / "bad_schema.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ManifestApplicationError, match="integrity check failed"):
        load_manifest(str(path))


def test_load_manifest_missing_required_field_raises(tmp_path):
    payload = {
        "schema_version": _SCHEMA_VERSION,
        # manifest_id is missing
        "project_id": "p",
        "generated_actions": [],
    }
    path = tmp_path / "missing_field.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ManifestApplicationError, match="integrity check failed"):
        load_manifest(str(path))


def test_load_manifest_generated_actions_not_list_raises(tmp_path):
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "manifest_id": "x",
        "project_id": "p",
        "generated_actions": "not_a_list",
    }
    path = tmp_path / "bad_actions.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ManifestApplicationError, match="integrity check failed"):
        load_manifest(str(path))


# ---------------------------------------------------------------------------
# Test 2 — generate_reviewed_manifest does NOT mutate original manifest
# ---------------------------------------------------------------------------

def test_generate_reviewed_manifest_does_not_mutate_original(tmp_path):
    manifest_path = _make_manifest_file(tmp_path)
    original_raw = json.loads(open(manifest_path, encoding="utf-8").read())
    original_copy = copy.deepcopy(original_raw)

    approvals = {"act_000000000001": {"status": "approved", "approved_by": "me", "note": ""}}
    generate_reviewed_manifest(manifest_path, approvals, str(tmp_path))

    # Original file must be unchanged
    reloaded = json.loads(open(manifest_path, encoding="utf-8").read())
    assert reloaded == original_copy, "Original manifest file was mutated"


def test_generate_reviewed_manifest_produces_separate_artifact(tmp_path):
    manifest_path = _make_manifest_file(tmp_path)
    approvals = {"act_000000000001": {"status": "approved", "approved_by": "me", "note": ""}}
    reviewed = generate_reviewed_manifest(manifest_path, approvals, str(tmp_path))

    cache_dir = os.path.join(str(tmp_path), ".cache", "reviewed_manifests")
    files = [f for f in os.listdir(cache_dir) if f.endswith(".json")]
    assert len(files) == 1
    assert reviewed.reviewed_manifest_id in files[0]


def test_generate_reviewed_manifest_writes_explicit_output_path(tmp_path):
    manifest_path = _make_manifest_file(tmp_path)
    approvals = {"act_000000000001": {"status": "approved", "approved_by": "me", "note": ""}}
    reviewed_out = tmp_path / "reviewed_explicit.json"

    reviewed = generate_reviewed_manifest(manifest_path, approvals, str(tmp_path), out_path=str(reviewed_out))

    assert reviewed_out.exists()
    payload = json.loads(reviewed_out.read_text(encoding="utf-8"))
    assert payload["reviewed_manifest_id"] == reviewed.reviewed_manifest_id


def test_load_approvals_file_invalid_status_raises(tmp_path):
    approvals_path = tmp_path / "approvals.json"
    approvals_path.write_text(
        json.dumps({"act_1": {"status": "invalid", "approved_by": "me", "note": ""}}),
        encoding="utf-8",
    )

    with pytest.raises(ManifestApplicationError, match="invalid status"):
        load_approvals_file(str(approvals_path))


# ---------------------------------------------------------------------------
# Test 3 — Per-action approval works
# ---------------------------------------------------------------------------

def test_approved_action_status_approved(tmp_path):
    manifest_path = _make_manifest_file(tmp_path)
    approvals = {"act_000000000001": {"status": "approved", "approved_by": "alice", "note": "LGTM"}}
    reviewed = generate_reviewed_manifest(manifest_path, approvals, str(tmp_path))
    assert len(reviewed.approved_actions) == 1
    assert reviewed.approved_actions[0].approval_status == "approved"
    assert reviewed.approved_actions[0].approved_by == "alice"
    assert reviewed.approved_actions[0].approval_note == "LGTM"


def test_rejected_action_status_rejected(tmp_path):
    manifest_path = _make_manifest_file(tmp_path)
    approvals = {"act_000000000001": {"status": "rejected", "approved_by": "bob", "note": "no"}}
    reviewed = generate_reviewed_manifest(manifest_path, approvals, str(tmp_path))
    assert reviewed.approved_actions[0].approval_status == "rejected"


def test_missing_from_approvals_defaults_to_pending(tmp_path):
    manifest_path = _make_manifest_file(tmp_path)
    # provide no approvals for the action
    reviewed = generate_reviewed_manifest(manifest_path, {}, str(tmp_path))
    assert reviewed.approved_actions[0].approval_status == "pending"


def test_invalid_status_defaults_to_pending(tmp_path):
    manifest_path = _make_manifest_file(tmp_path)
    approvals = {"act_000000000001": {"status": "INVALID_STATUS", "approved_by": "x", "note": ""}}
    reviewed = generate_reviewed_manifest(manifest_path, approvals, str(tmp_path))
    assert reviewed.approved_actions[0].approval_status == "pending"


def test_approved_value_equals_suggested_value(tmp_path):
    """approved_value must always equal the original suggested_value (never substituted)."""
    manifest_path = _make_manifest_file(tmp_path)
    approvals = {"act_000000000001": {"status": "approved", "approved_by": "x", "note": ""}}
    reviewed = generate_reviewed_manifest(manifest_path, approvals, str(tmp_path))
    action = reviewed.approved_actions[0]
    assert action.approved_value is True   # == suggested_value from manifest


# ---------------------------------------------------------------------------
# Test 4 — Only "approved" actions are applied
# ---------------------------------------------------------------------------

def test_apply_manifest_applies_approved_action(tmp_path):
    manifest_path = _make_manifest_file(tmp_path, manifest_id="mfst_apply_001")
    reviewed_path = _make_reviewed_manifest_file(
        tmp_path, source_manifest_id="mfst_apply_001",
        reviewed_manifest_id="rev_apply_001",
    )
    config_path = _make_config_file(tmp_path, {"calibration": {"enabled": False}})

    receipt = apply_manifest(reviewed_path, manifest_path, config_path, str(tmp_path))

    assert "act_000000000001" in receipt.applied_actions
    # Config file should now have calibration.enabled = True
    final_config = json.loads(open(config_path, encoding="utf-8").read())
    assert final_config["calibration"]["enabled"] is True


# ---------------------------------------------------------------------------
# Test 5 — "pending" and "rejected" actions are skipped
# ---------------------------------------------------------------------------

def test_pending_action_is_skipped(tmp_path):
    manifest_path = _make_manifest_file(tmp_path, manifest_id="mfst_skip_p")
    reviewed_path = _make_reviewed_manifest_file(
        tmp_path, source_manifest_id="mfst_skip_p",
        reviewed_manifest_id="rev_skip_p",
        actions=[{
            "action_id": "act_000000000001",
            "proposal_id": "prop_abc123",
            "action_type": "config_suggestion",
            "target_config_key": "calibration.enabled",
            "current_value": False,
            "approved_value": True,
            "approval_status": "pending",
            "rollback_key": "calibration.enabled",
            "approved_by": "",
            "approval_note": "",
        }],
    )
    config_path = _make_config_file(tmp_path, {"calibration": {"enabled": False}})

    receipt = apply_manifest(reviewed_path, manifest_path, config_path, str(tmp_path))

    assert "act_000000000001" in receipt.skipped_actions
    assert "act_000000000001" not in receipt.applied_actions
    # Config must be unchanged
    final_config = json.loads(open(config_path, encoding="utf-8").read())
    assert final_config["calibration"]["enabled"] is False


def test_rejected_action_is_skipped(tmp_path):
    manifest_path = _make_manifest_file(tmp_path, manifest_id="mfst_skip_r")
    reviewed_path = _make_reviewed_manifest_file(
        tmp_path, source_manifest_id="mfst_skip_r",
        reviewed_manifest_id="rev_skip_r",
        actions=[{
            "action_id": "act_000000000001",
            "proposal_id": "prop_abc123",
            "action_type": "config_suggestion",
            "target_config_key": "calibration.enabled",
            "current_value": False,
            "approved_value": True,
            "approval_status": "rejected",
            "rollback_key": "calibration.enabled",
            "approved_by": "bob",
            "approval_note": "nope",
        }],
    )
    config_path = _make_config_file(tmp_path, {"calibration": {"enabled": False}})

    receipt = apply_manifest(reviewed_path, manifest_path, config_path, str(tmp_path))

    assert "act_000000000001" in receipt.skipped_actions
    assert "act_000000000001" not in receipt.applied_actions


def test_no_approved_actions_leaves_config_unchanged(tmp_path):
    manifest_path = _make_manifest_file(tmp_path, manifest_id="mfst_noop")
    reviewed_path = _make_reviewed_manifest_file(
        tmp_path, source_manifest_id="mfst_noop",
        reviewed_manifest_id="rev_noop",
        actions=[{
            "action_id": "act_000000000001",
            "proposal_id": "prop_abc123",
            "action_type": "config_suggestion",
            "target_config_key": "calibration.enabled",
            "current_value": False,
            "approved_value": True,
            "approval_status": "pending",
            "rollback_key": "calibration.enabled",
            "approved_by": "",
            "approval_note": "",
        }],
    )
    original_config = {"calibration": {"enabled": False}}
    config_path = _make_config_file(tmp_path, copy.deepcopy(original_config))

    apply_manifest(reviewed_path, manifest_path, config_path, str(tmp_path))

    final_config = json.loads(open(config_path, encoding="utf-8").read())
    assert final_config == original_config, "Config should not change when no actions are approved"


# ---------------------------------------------------------------------------
# Test 6 — Unsupported action_type raises ManifestApplicationError
# ---------------------------------------------------------------------------

def test_unsupported_action_type_in_reviewed_manifest_raises(tmp_path):
    manifest_path = _make_manifest_file(
        tmp_path, manifest_id="mfst_badtype",
        actions=[_default_action_dict(action_type="unsupported_type")],
    )
    reviewed_path = _make_reviewed_manifest_file(
        tmp_path, source_manifest_id="mfst_badtype",
        reviewed_manifest_id="rev_badtype",
        actions=[{
            "action_id": "act_000000000001",
            "proposal_id": "prop_abc123",
            "action_type": "unsupported_type",
            "target_config_key": "calibration.enabled",
            "current_value": False,
            "approved_value": True,
            "approval_status": "approved",
            "rollback_key": "calibration.enabled",
            "approved_by": "x",
            "approval_note": "",
        }],
    )
    config_path = _make_config_file(tmp_path)

    with pytest.raises(ManifestApplicationError, match="Unsupported action_type"):
        apply_manifest(reviewed_path, manifest_path, config_path, str(tmp_path))


def test_validate_approved_action_unsupported_type():
    action = _make_approved_action(action_type="auto_apply", target_config_key="calibration.enabled")
    errors = _validate_approved_action(action)
    assert any("unsupported action_type" in e for e in errors)


def test_apply_single_action_returns_error_on_unsupported_type():
    """_apply_single_action validates first; unsupported type yields a soft error string
    (not a raise) because _validate_approved_action intercepts it before the hard-raise path.
    The hard raise fires only from apply_manifest() when the action passes validation
    but has an unsupported type — that path is covered by test_unsupported_action_type_in_reviewed_manifest_raises."""
    action = _make_approved_action(action_type="unsupported_xyz")
    config = {"calibration": {"enabled": False}}
    new_config, rollback, error = _apply_single_action(action, config, "pending")
    assert error is not None
    assert rollback is None
    assert new_config == config


# ---------------------------------------------------------------------------
# Test 7 — Forbidden target is re-checked independently and blocked
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_key", [
    "decision_engine.threshold",
    "routing.table",
    "calibration.mode",
    "calibration.max_adjustment",
    "calibration.thresholds.x",
    "context_profile.x",
    "arabic.routing",
    "conflict.x",
    "enforcement.x",
    "output.x",
    "results_dir",
    "report.format",
    "review_queue.path",
    "score_finding.weights",
])
def test_recheck_forbidden_target_blocked(bad_key):
    assert _recheck_forbidden_target(bad_key), f"Expected {bad_key!r} to be forbidden"


def test_calibration_enabled_not_forbidden():
    assert not _recheck_forbidden_target("calibration.enabled")


def test_validate_approved_action_forbids_bad_target():
    action = _make_approved_action(
        target_config_key="routing.main",
        rollback_key="routing.main",
    )
    errors = _validate_approved_action(action)
    # Should fail both the allowlist check and the forbidden re-check
    assert any("not in the" in e or "forbidden" in e for e in errors)


def test_validate_approved_action_target_not_in_allowed_set():
    action = _make_approved_action(
        target_config_key="some.other.key",
        rollback_key="some.other.key",
    )
    errors = _validate_approved_action(action)
    assert any("not in the" in e for e in errors)


def test_apply_single_action_blocked_by_validation():
    """Forbidden/unlisted target causes a soft failure (error string), not a raise."""
    action = _make_approved_action(
        target_config_key="routing.table",
        rollback_key="routing.table",
    )
    config = {"routing": {"table": "old"}}
    new_config, rollback, error = _apply_single_action(action, config, "pending")
    assert error is not None
    assert rollback is None
    # Config must be unchanged
    assert new_config == config


# ---------------------------------------------------------------------------
# Test 8 — Receipt artifact persisted BEFORE config file is replaced
# ---------------------------------------------------------------------------

def test_receipt_exists_before_config_committed(tmp_path, monkeypatch):
    """Intercept the second atomic write (config) and verify receipt file already exists."""
    manifest_path = _make_manifest_file(tmp_path, manifest_id="mfst_order")
    reviewed_path = _make_reviewed_manifest_file(
        tmp_path, source_manifest_id="mfst_order", reviewed_manifest_id="rev_order",
    )
    config_path = _make_config_file(tmp_path, {"calibration": {"enabled": False}})

    receipt_seen_before_config = []

    import l10n_audit.core.manifest_application as _mod
    original_atomic_write = _mod._atomic_write_json

    call_count = [0]

    def _spy_atomic_write(path, payload):
        call_count[0] += 1
        original_atomic_write(path, payload)
        if call_count[0] == 1:
            # This is the receipt write — it should create the receipts cache dir
            receipt_cache = os.path.join(str(tmp_path), ".cache", "application_receipts")
            files = os.listdir(receipt_cache) if os.path.isdir(receipt_cache) else []
            receipt_seen_before_config.append(len(files) > 0)

    monkeypatch.setattr(_mod, "_atomic_write_json", _spy_atomic_write)

    apply_manifest(reviewed_path, manifest_path, config_path, str(tmp_path))

    assert receipt_seen_before_config == [True], (
        "Receipt file must exist after the first atomic write (before config commit)"
    )


def test_receipt_file_written_to_cache(tmp_path):
    manifest_path = _make_manifest_file(tmp_path, manifest_id="mfst_rcpt")
    reviewed_path = _make_reviewed_manifest_file(
        tmp_path, source_manifest_id="mfst_rcpt", reviewed_manifest_id="rev_rcpt",
    )
    config_path = _make_config_file(tmp_path, {"calibration": {"enabled": False}})

    receipt = apply_manifest(reviewed_path, manifest_path, config_path, str(tmp_path))

    receipt_cache = os.path.join(str(tmp_path), ".cache", "application_receipts")
    assert os.path.isdir(receipt_cache)
    files = [f for f in os.listdir(receipt_cache) if f.endswith(".json")]
    assert len(files) == 1
    assert receipt.receipt_id in files[0]


# ---------------------------------------------------------------------------
# Test 9 — Config writes are atomic (no .tmp files left behind)
# ---------------------------------------------------------------------------

def test_no_tmp_files_left_after_apply(tmp_path):
    manifest_path = _make_manifest_file(tmp_path, manifest_id="mfst_atomic")
    reviewed_path = _make_reviewed_manifest_file(
        tmp_path, source_manifest_id="mfst_atomic", reviewed_manifest_id="rev_atomic",
    )
    config_path = _make_config_file(tmp_path, {"calibration": {"enabled": False}})

    apply_manifest(reviewed_path, manifest_path, config_path, str(tmp_path))

    tmp_files = [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")]
    assert tmp_files == [], f"Leftover .tmp files found: {tmp_files}"


def test_no_tmp_files_in_cache_after_apply(tmp_path):
    manifest_path = _make_manifest_file(tmp_path, manifest_id="mfst_atomc2")
    reviewed_path = _make_reviewed_manifest_file(
        tmp_path, source_manifest_id="mfst_atomc2", reviewed_manifest_id="rev_atomc2",
    )
    config_path = _make_config_file(tmp_path, {"calibration": {"enabled": False}})

    apply_manifest(reviewed_path, manifest_path, config_path, str(tmp_path))

    cache = os.path.join(str(tmp_path), ".cache", "application_receipts")
    tmp_files = [f for f in os.listdir(cache) if f.endswith(".tmp")] if os.path.isdir(cache) else []
    assert tmp_files == [], f"Leftover .tmp files in cache: {tmp_files}"


def test_rollback_no_tmp_files_left(tmp_path):
    manifest_path = _make_manifest_file(tmp_path, manifest_id="mfst_rtmp")
    reviewed_path = _make_reviewed_manifest_file(
        tmp_path, source_manifest_id="mfst_rtmp", reviewed_manifest_id="rev_rtmp",
    )
    config_path = _make_config_file(tmp_path, {"calibration": {"enabled": False}})
    receipt = apply_manifest(reviewed_path, manifest_path, config_path, str(tmp_path))

    receipt_cache = os.path.join(str(tmp_path), ".cache", "application_receipts")
    receipt_path = os.path.join(receipt_cache, f"proj_test_{receipt.receipt_id}.json")
    rollback_application(receipt_path, config_path)

    tmp_files = [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")]
    assert tmp_files == []


# ---------------------------------------------------------------------------
# Test 10 — Rollback restores previous_value from live config snapshot
# ---------------------------------------------------------------------------

def test_rollback_restores_live_config_not_stale_p15_value(tmp_path):
    """
    The key insight: rollback uses previous_value captured from the live config
    at application time — not the stale current_value from Phase 15.
    Here, the live config has enabled=True while the Phase 15 current_value
    in the manifest says False. After apply + rollback, we expect True (live).
    """
    # Manifest says current_value=False (stale Phase 15 snapshot)
    manifest_path = _make_manifest_file(
        tmp_path, manifest_id="mfst_rb",
        actions=[_default_action_dict(current_value=False)],  # stale
    )
    reviewed_path = _make_reviewed_manifest_file(
        tmp_path, source_manifest_id="mfst_rb", reviewed_manifest_id="rev_rb",
    )
    # But live config actually has enabled=True (updated since P15 ran)
    config_path = _make_config_file(tmp_path, {"calibration": {"enabled": True}})

    receipt = apply_manifest(reviewed_path, manifest_path, config_path, str(tmp_path))

    # Verify the rollback record captured the live value (True), not Phase 15 stale (False)
    assert len(receipt.rollback_records) == 1
    assert receipt.rollback_records[0].previous_value is True

    # Now rollback — should restore to True (live), not False (stale)
    receipt_cache = os.path.join(str(tmp_path), ".cache", "application_receipts")
    receipt_path = os.path.join(receipt_cache, f"proj_test_{receipt.receipt_id}.json")
    rollback_application(receipt_path, config_path)

    restored = json.loads(open(config_path, encoding="utf-8").read())
    assert restored["calibration"]["enabled"] is True


def test_rollback_with_none_previous_value(tmp_path):
    """When the key didn't exist before, rollback sets it to None (key created, not deleted)."""
    manifest_path = _make_manifest_file(tmp_path, manifest_id="mfst_rbnull")
    reviewed_path = _make_reviewed_manifest_file(
        tmp_path, source_manifest_id="mfst_rbnull", reviewed_manifest_id="rev_rbnull",
    )
    # Config has no 'calibration' key at all -> previous_value will be None
    config_path = _make_config_file(tmp_path, {})

    receipt = apply_manifest(reviewed_path, manifest_path, config_path, str(tmp_path))

    assert receipt.rollback_records[0].previous_value is None

    receipt_cache = os.path.join(str(tmp_path), ".cache", "application_receipts")
    receipt_path = os.path.join(receipt_cache, f"proj_test_{receipt.receipt_id}.json")
    rollback_application(receipt_path, config_path)

    restored = json.loads(open(config_path, encoding="utf-8").read())
    # After rollback the key path exists but holds None
    assert restored["calibration"]["enabled"] is None


def test_rollback_empty_records_is_noop(tmp_path):
    receipt_data = {
        "receipt_id": "noop",
        "schema_version": _SCHEMA_VERSION,
        "source_manifest_id": "m",
        "source_reviewed_manifest_id": "r",
        "project_id": "p",
        "config_path": "/fake",
        "config_before_hash": "a",
        "config_after_hash": "a",
        "applied_actions": [],
        "skipped_actions": [],
        "failed_actions": [],
        "rollback_records": [],
        "rollback_ready": True,
    }
    receipt_path = str(tmp_path / "receipt_noop.json")
    with open(receipt_path, "w") as fh:
        json.dump(receipt_data, fh)

    config_path = _make_config_file(tmp_path, {"x": 1})
    original = json.loads(open(config_path).read())
    rollback_application(receipt_path, config_path)
    after = json.loads(open(config_path).read())
    assert after == original


def test_rollback_ready_only_when_all_applied_have_records(tmp_path):
    manifest_path = _make_manifest_file(tmp_path, manifest_id="mfst_rr")
    reviewed_path = _make_reviewed_manifest_file(
        tmp_path, source_manifest_id="mfst_rr", reviewed_manifest_id="rev_rr",
    )
    config_path = _make_config_file(tmp_path, {"calibration": {"enabled": False}})

    receipt = apply_manifest(reviewed_path, manifest_path, config_path, str(tmp_path))

    applied_count = len(receipt.applied_actions)
    rollback_count = len(receipt.rollback_records)
    assert receipt.rollback_ready == (rollback_count == applied_count)


# ---------------------------------------------------------------------------
# Test 11 — Deterministic reviewed_manifest_id and receipt_id
# ---------------------------------------------------------------------------

def test_reviewed_manifest_id_is_deterministic(tmp_path):
    manifest_path = _make_manifest_file(tmp_path, manifest_id="mfst_det")
    approvals = {"act_000000000001": {"status": "approved", "approved_by": "x", "note": ""}}
    r1 = generate_reviewed_manifest(manifest_path, approvals, str(tmp_path))
    r2 = generate_reviewed_manifest(manifest_path, approvals, str(tmp_path))
    assert r1.reviewed_manifest_id == r2.reviewed_manifest_id


def test_receipt_id_is_deterministic(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    manifest_path_a = _make_manifest_file(dir_a, manifest_id="mfst_deta")
    manifest_path_b = _make_manifest_file(dir_b, manifest_id="mfst_deta")
    rev_a = _make_reviewed_manifest_file(
        dir_a, source_manifest_id="mfst_deta", reviewed_manifest_id="rev_deta",
    )
    rev_b = _make_reviewed_manifest_file(
        dir_b, source_manifest_id="mfst_deta", reviewed_manifest_id="rev_deta",
    )
    cfg_a = _make_config_file(dir_a, {"calibration": {"enabled": False}})
    cfg_b = _make_config_file(dir_b, {"calibration": {"enabled": False}})

    receipt_a = apply_manifest(rev_a, manifest_path_a, cfg_a, str(dir_a))
    receipt_b = apply_manifest(rev_b, manifest_path_b, cfg_b, str(dir_b))
    assert receipt_a.receipt_id == receipt_b.receipt_id


def test_build_reviewed_manifest_id_stable():
    actions = [_make_approved_action()]
    id1 = _build_reviewed_manifest_id("mfst001", actions)
    id2 = _build_reviewed_manifest_id("mfst001", actions)
    assert id1 == id2


def test_build_receipt_id_stable():
    id1 = _build_receipt_id("m", "r", ["act1", "act2"])
    id2 = _build_receipt_id("m", "r", ["act1", "act2"])
    assert id1 == id2


def test_different_approvals_different_reviewed_manifest_id(tmp_path):
    manifest_path = _make_manifest_file(tmp_path, manifest_id="mfst_diff")
    app_a = {"act_000000000001": {"status": "approved", "approved_by": "x", "note": ""}}
    app_b = {"act_000000000001": {"status": "rejected", "approved_by": "x", "note": ""}}
    r1 = generate_reviewed_manifest(manifest_path, app_a, str(tmp_path))
    r2 = generate_reviewed_manifest(manifest_path, app_b, str(tmp_path))
    assert r1.reviewed_manifest_id != r2.reviewed_manifest_id


# ---------------------------------------------------------------------------
# Test 12 — No mutation of input manifest dict / config
# ---------------------------------------------------------------------------

def test_set_dotted_key_does_not_mutate_input():
    original = {"calibration": {"enabled": False}}
    before = copy.deepcopy(original)
    result = _set_dotted_key(original, "calibration.enabled", True)
    assert original == before, "_set_dotted_key mutated the input dict"
    assert result["calibration"]["enabled"] is True


def test_apply_single_action_does_not_mutate_input_config():
    action = _make_approved_action()
    config = {"calibration": {"enabled": False}}
    before = copy.deepcopy(config)
    _apply_single_action(action, config, "pending")
    assert config == before, "_apply_single_action mutated the input config"


def test_generate_reviewed_manifest_does_not_mutate_approvals_dict(tmp_path):
    manifest_path = _make_manifest_file(tmp_path, manifest_id="mfst_nomu")
    approvals = {"act_000000000001": {"status": "approved", "approved_by": "x", "note": ""}}
    approvals_before = copy.deepcopy(approvals)
    generate_reviewed_manifest(manifest_path, approvals, str(tmp_path))
    assert approvals == approvals_before


# ---------------------------------------------------------------------------
# Test 13 — No dependency on engine.py or runtime pipeline
# ---------------------------------------------------------------------------

def test_manifest_application_not_imported_by_engine():
    import l10n_audit.core.engine as eng
    assert "manifest_application" not in dir(eng)


def test_manifest_application_not_imported_by_decision_engine():
    import l10n_audit.core.decision_engine as de
    assert "manifest_application" not in dir(de)


def test_manifest_application_not_imported_by_calibration_engine():
    import l10n_audit.core.calibration_engine as ce
    assert "manifest_application" not in dir(ce)


def test_manifest_application_not_imported_by_controlled_consumption():
    import l10n_audit.core.controlled_consumption as cc
    assert "manifest_application" not in dir(cc)


def test_manifest_application_not_imported_by_adaptation_intelligence():
    import l10n_audit.core.adaptation_intelligence as ai
    assert "manifest_application" not in dir(ai)


# ---------------------------------------------------------------------------
# Test 14 — No changes to existing outputs/tests (isolation verification)
# ---------------------------------------------------------------------------

def test_apply_manifest_cross_check_manifest_ids_mismatch_raises(tmp_path):
    """apply_manifest must raise if reviewed_manifest references a different source manifest."""
    real_manifest_path = _make_manifest_file(tmp_path, manifest_id="real_mfst")
    reviewed_path = _make_reviewed_manifest_file(
        tmp_path, source_manifest_id="DIFFERENT_MFST_ID", reviewed_manifest_id="rev_mism",
    )
    config_path = _make_config_file(tmp_path)
    with pytest.raises(ManifestApplicationError, match="does not match"):
        apply_manifest(reviewed_path, real_manifest_path, config_path, str(tmp_path))


def test_apply_manifest_config_not_json_object_raises(tmp_path):
    manifest_path = _make_manifest_file(tmp_path, manifest_id="mfst_badcfg")
    reviewed_path = _make_reviewed_manifest_file(
        tmp_path, source_manifest_id="mfst_badcfg", reviewed_manifest_id="rev_badcfg",
    )
    config_path = str(tmp_path / "bad_config.json")
    with open(config_path, "w") as fh:
        json.dump([1, 2, 3], fh)  # list, not object
    with pytest.raises(ManifestApplicationError, match="JSON object"):
        apply_manifest(reviewed_path, manifest_path, config_path, str(tmp_path))


def test_receipt_config_before_and_after_hashes_differ_when_applied(tmp_path):
    manifest_path = _make_manifest_file(tmp_path, manifest_id="mfst_hash")
    reviewed_path = _make_reviewed_manifest_file(
        tmp_path, source_manifest_id="mfst_hash", reviewed_manifest_id="rev_hash",
    )
    config_path = _make_config_file(tmp_path, {"calibration": {"enabled": False}})

    receipt = apply_manifest(reviewed_path, manifest_path, config_path, str(tmp_path))

    assert receipt.config_before_hash != receipt.config_after_hash


def test_receipt_hashes_same_when_no_actions_applied(tmp_path):
    manifest_path = _make_manifest_file(tmp_path, manifest_id="mfst_sameha")
    reviewed_path = _make_reviewed_manifest_file(
        tmp_path, source_manifest_id="mfst_sameha", reviewed_manifest_id="rev_sameha",
        actions=[{
            "action_id": "act_000000000001",
            "proposal_id": "prop_abc123",
            "action_type": "config_suggestion",
            "target_config_key": "calibration.enabled",
            "current_value": False,
            "approved_value": True,
            "approval_status": "pending",
            "rollback_key": "calibration.enabled",
            "approved_by": "",
            "approval_note": "",
        }],
    )
    config_path = _make_config_file(tmp_path, {"calibration": {"enabled": False}})

    receipt = apply_manifest(reviewed_path, manifest_path, config_path, str(tmp_path))

    assert receipt.config_before_hash == receipt.config_after_hash


# ---------------------------------------------------------------------------
# Additional pure helper tests
# ---------------------------------------------------------------------------

def test_hash_content_stable():
    h1 = _hash_content({"a": 1, "b": [1, 2, 3]})
    h2 = _hash_content({"b": [1, 2, 3], "a": 1})
    assert h1 == h2  # sort_keys=True ensures order-independence


def test_hash_config_16_chars():
    h = _hash_config({"x": True})
    assert len(h) == 16


def test_resolve_dotted_key_nested():
    cfg = {"a": {"b": {"c": 42}}}
    parent, parts, exists = _resolve_dotted_key(cfg, "a.b.c")
    assert exists
    assert parent["c"] == 42


def test_resolve_dotted_key_missing():
    cfg = {}
    parent, parts, exists = _resolve_dotted_key(cfg, "a.b.c")
    assert not exists


def test_get_dotted_value_present():
    cfg = {"calibration": {"enabled": False}}
    assert _get_dotted_value(cfg, "calibration.enabled") is False


def test_get_dotted_value_absent():
    assert _get_dotted_value({}, "calibration.enabled") is None


def test_set_dotted_key_creates_intermediate_dicts():
    cfg = {}
    result = _set_dotted_key(cfg, "a.b.c", 99)
    assert result["a"]["b"]["c"] == 99
    assert cfg == {}  # original unmutated


def test_validate_manifest_integrity_valid():
    errors = _validate_manifest_integrity({
        "schema_version": "1.0",
        "manifest_id": "x",
        "project_id": "p",
        "generated_actions": [],
    })
    assert errors == []


def test_validate_manifest_integrity_not_dict():
    errors = _validate_manifest_integrity("bad")
    assert "not a dict" in errors[0]


def test_rollback_key_must_equal_target_config_key():
    action = _make_approved_action(rollback_key="some.other.key")
    errors = _validate_approved_action(action)
    assert any("rollback_key" in e for e in errors)
