"""
l10n_audit/core/manifest_application.py
=========================================
Phase 16 — Human-Approved Manifest Application Layer.

Design constraints
------------------
* Explicit offline workflow only — never called during `run`.
* NOT integrated into engine.py — no pipeline hook of any kind.
* Reads ConsumptionManifest (Phase 15 output) from disk, never from runtime.
* Only applies actions with approval_status == "approved".
* Only supports action_type == "config_suggestion" in v1.
* Only applies to safe target keys; forbidden targets re-checked independently.
* Original ConsumptionManifest is never mutated.
* Config writes are atomic via .tmp + os.replace().
* Rollback artifact is persisted BEFORE the config file is replaced (critical ordering).
* Rollback uses previous_value captured from live config at application time,
  not stale current_value from Phase 15 manifest generation time.
* Deterministic: same manifest + same approvals + same config snapshot → same receipt.
* No wall-clock timestamps in semantic payload.

Dependency direction (one-way, enforced):
  explicit review/apply workflow → manifest_application
  ← NO reverse dependency allowed ←
  Must NOT be imported by: decision_engine, calibration_engine, context_profile,
  conflict_resolution, enforcement_layer, adaptation_intelligence,
  controlled_consumption, project_memory, engine.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("l10n_audit.manifest_application")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCHEMA_VERSION = "1.0"

# Only config_suggestion is supported in Phase 16 v1.
# Any other action_type encountered must raise ManifestApplicationError.
_SUPPORTED_ACTION_TYPES: frozenset = frozenset({"config_suggestion"})

# Approved target keys in v1. Anything not in this set is rejected.
# This is a positive allowlist — failure is the default.
_ALLOWED_TARGET_KEYS: frozenset = frozenset({
    "calibration.enabled",
})

# Forbidden target prefixes — mirrors Phase 15's _FORBIDDEN_TARGET_PREFIXES.
# Re-checked independently here; Phase 16 does NOT trust Phase 15's safety flags.
_FORBIDDEN_TARGET_PREFIXES: Tuple[str, ...] = (
    "decision_engine",
    "routing",
    "score_finding",
    "calibration.mode",
    "calibration.max_adjustment",
    "calibration.thresholds",
    "context_profile",
    "context_rules",
    "arabic",
    "conflict",
    "enforcement",
    "output",
    "results_dir",
    "report",
    "review_queue",
)

_APPROVAL_STATUSES: frozenset = frozenset({"approved", "rejected", "pending"})


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ManifestApplicationError(Exception):
    """Raised when Phase 16 cannot proceed safely.

    Covers: corrupt manifest, unsupported action type, forbidden targets,
    invalid approval state, config write failures that could not be recovered.
    Never raised for ordinary skip/reject decisions (those are recorded in receipt).
    """


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class ApprovedAction:
    """Human-reviewed disposition of a single ConsumableAction.

    approved_value always equals the original suggested_value.
    Humans approve or reject — they do not substitute custom values in v1.
    rollback_key always equals target_config_key.
    """
    action_id: str
    proposal_id: str
    action_type: str
    target_config_key: str
    current_value: Any              # from ConsumableAction.current_value (P15 generation time)
    approved_value: Any             # always == ConsumableAction.suggested_value
    approval_status: str            # "approved" | "rejected" | "pending"
    rollback_key: str               # always == target_config_key
    approved_by: str                # free-text human identity (not validated)
    approval_note: str              # free-text rationale (may be empty)


@dataclass
class ReviewedManifest:
    """Companion to ConsumptionManifest carrying per-action human decisions.

    The original ConsumptionManifest file is never modified.
    This object is a separate artifact that references it by source_manifest_id.
    reviewed_manifest_id is deterministic: same source_manifest_id + same
    approved_actions → same id.
    """
    reviewed_manifest_id: str
    schema_version: str
    source_manifest_id: str
    project_id: str
    approved_actions: List[ApprovedAction] = field(default_factory=list)


@dataclass
class RollbackRecord:
    """Captures live previous_value for a single applied action.

    previous_value is captured from the live config at application time —
    NOT from ConsumableAction.current_value (which may be stale).
    rollback_key always equals target_config_key.
    """
    receipt_id: str
    action_id: str
    target_config_key: str
    previous_value: Any             # captured from live config before patching
    applied_value: Any              # what was written
    rollback_key: str               # always == target_config_key


@dataclass
class ApplicationReceipt:
    """Deterministic record of what was applied, skipped, or failed.

    config_before_hash and config_after_hash allow verification that no
    unintended changes were made.
    rollback_ready is True only when every applied_action has a corresponding
    RollbackRecord with a captured previous_value.
    No wall-clock timestamp in the semantic payload.
    """
    receipt_id: str
    schema_version: str
    source_manifest_id: str
    source_reviewed_manifest_id: str
    project_id: str
    config_path: str
    config_before_hash: str
    config_after_hash: str
    applied_actions: List[str] = field(default_factory=list)    # action_ids
    skipped_actions: List[str] = field(default_factory=list)    # action_ids
    failed_actions: List[str] = field(default_factory=list)     # action_ids
    rollback_records: List[RollbackRecord] = field(default_factory=list)
    rollback_ready: bool = False


# ---------------------------------------------------------------------------
# Pure helpers — all deterministic, all side-effect-free
# ---------------------------------------------------------------------------

def _hash_content(data: Any) -> str:
    """Stable 16-char hex digest of any JSON-serialisable payload."""
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _hash_config(config_dict: Dict[str, Any]) -> str:
    """Stable 16-char hex digest of a config dict."""
    return _hash_content(config_dict)


def _build_reviewed_manifest_id(source_manifest_id: str,
                                 approved_actions: List[ApprovedAction]) -> str:
    """Deterministic id from source_manifest_id + sorted action dispositions."""
    payload = {
        "source_manifest_id": source_manifest_id,
        "actions": sorted(
            [{"action_id": a.action_id, "status": a.approval_status}
             for a in approved_actions],
            key=lambda x: x["action_id"],
        ),
    }
    return _hash_content(payload)[:12]


def _build_receipt_id(source_manifest_id: str, reviewed_manifest_id: str,
                      applied_action_ids: List[str]) -> str:
    """Deterministic id from manifest ids + sorted applied action ids."""
    payload = {
        "source_manifest_id": source_manifest_id,
        "reviewed_manifest_id": reviewed_manifest_id,
        "applied_action_ids": sorted(applied_action_ids),
    }
    return _hash_content(payload)[:12]


def _recheck_forbidden_target(key: str) -> bool:
    """Return True if key matches any forbidden target prefix.

    Runs independently of Phase 15 — Phase 16 never trusts safety_checks_passed.
    """
    k = key.strip().lower()
    for prefix in _FORBIDDEN_TARGET_PREFIXES:
        if k == prefix or k.startswith(prefix + ".") or k.startswith(prefix + "_"):
            return True
    return False


def _resolve_dotted_key(config_dict: Dict[str, Any],
                         key: str) -> Tuple[Any, List[str], bool]:
    """Traverse a dotted key path in a nested dict.

    Returns (parent_dict_or_None, parts, key_exists).
    Does not mutate config_dict.
    """
    parts = key.split(".")
    obj: Any = config_dict
    for part in parts[:-1]:
        if not isinstance(obj, dict):
            return None, parts, False
        obj = obj.get(part)
        if obj is None:
            return None, parts, False
    if not isinstance(obj, dict):
        return None, parts, False
    exists = parts[-1] in obj
    return obj, parts, exists


def _get_dotted_value(config_dict: Dict[str, Any], key: str) -> Any:
    """Return the value at a dotted key path, or None if absent."""
    parent, parts, exists = _resolve_dotted_key(config_dict, key)
    if parent is None or not exists:
        return None
    return parent[parts[-1]]


def _set_dotted_key(config_dict: Dict[str, Any], key: str, value: Any) -> Dict[str, Any]:
    """Return a new config dict with value set at the dotted key path.

    Creates intermediate dicts as needed — never mutates the input dict.
    Raises ManifestApplicationError if the path traversal fails at a non-dict node.
    """
    result = copy.deepcopy(config_dict)
    parts = key.split(".")
    obj: Any = result
    for part in parts[:-1]:
        if not isinstance(obj, dict):
            raise ManifestApplicationError(
                f"Cannot traverse config path {key!r}: "
                f"intermediate key {part!r} is not a dict"
            )
        if part not in obj or not isinstance(obj[part], dict):
            obj[part] = {}
        obj = obj[part]
    if not isinstance(obj, dict):
        raise ManifestApplicationError(
            f"Cannot set config path {key!r}: leaf parent is not a dict"
        )
    obj[parts[-1]] = value
    return result


# ---------------------------------------------------------------------------
# Validation helpers — all pure, all return lists of error strings
# ---------------------------------------------------------------------------

def _validate_manifest_integrity(manifest_dict: Dict[str, Any]) -> List[str]:
    """Validate that a raw manifest dict has the required fields and schema."""
    errors: List[str] = []
    if not isinstance(manifest_dict, dict):
        return ["manifest is not a dict"]
    if manifest_dict.get("schema_version") != _SCHEMA_VERSION:
        errors.append(
            f"unsupported schema_version {manifest_dict.get('schema_version')!r} "
            f"(expected {_SCHEMA_VERSION!r})"
        )
    for field_name in ("manifest_id", "project_id", "generated_actions"):
        if field_name not in manifest_dict:
            errors.append(f"missing required field {field_name!r}")
    if "generated_actions" in manifest_dict and not isinstance(
        manifest_dict["generated_actions"], list
    ):
        errors.append("generated_actions must be a list")
    return errors


def _validate_reviewed_manifest_integrity(reviewed: "ReviewedManifest") -> List[str]:
    """Validate a ReviewedManifest object before applying it."""
    errors: List[str] = []
    if not reviewed.source_manifest_id:
        errors.append("source_manifest_id is empty")
    if not reviewed.project_id:
        errors.append("project_id is empty")
    if not isinstance(reviewed.approved_actions, list):
        errors.append("approved_actions must be a list")
    if reviewed.schema_version != _SCHEMA_VERSION:
        errors.append(
            f"unsupported schema_version {reviewed.schema_version!r}"
        )
    return errors


def _validate_approved_action(action: "ApprovedAction") -> List[str]:
    """Validate a single ApprovedAction before attempting application."""
    errors: List[str] = []
    if action.action_type not in _SUPPORTED_ACTION_TYPES:
        errors.append(
            f"unsupported action_type {action.action_type!r}; "
            f"only {sorted(_SUPPORTED_ACTION_TYPES)} are supported in v1"
        )
    if action.target_config_key not in _ALLOWED_TARGET_KEYS:
        errors.append(
            f"target_config_key {action.target_config_key!r} is not in the "
            f"v1 allowed target set {sorted(_ALLOWED_TARGET_KEYS)}"
        )
    if _recheck_forbidden_target(action.target_config_key):
        errors.append(
            f"target_config_key {action.target_config_key!r} matches a "
            "forbidden target prefix (re-checked independently)"
        )
    if action.approval_status not in _APPROVAL_STATUSES:
        errors.append(
            f"invalid approval_status {action.approval_status!r}; "
            f"must be one of {sorted(_APPROVAL_STATUSES)}"
        )
    if action.rollback_key != action.target_config_key:
        errors.append(
            f"rollback_key {action.rollback_key!r} must equal "
            f"target_config_key {action.target_config_key!r}"
        )
    return errors


# ---------------------------------------------------------------------------
# Atomic file I/O helpers
# ---------------------------------------------------------------------------

def _atomic_write_json(path: str, payload: Any) -> None:
    """Write JSON atomically via .tmp + os.replace(). Creates parent dirs."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _load_json_file(path: str) -> Any:
    """Load and parse a JSON file. Raises ManifestApplicationError on failure."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise ManifestApplicationError(f"File not found: {path!r}")
    except json.JSONDecodeError as exc:
        raise ManifestApplicationError(f"Corrupt JSON at {path!r}: {exc}")


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _serialise_approved_action(a: ApprovedAction) -> Dict[str, Any]:
    return {
        "action_id":         a.action_id,
        "proposal_id":       a.proposal_id,
        "action_type":       a.action_type,
        "target_config_key": a.target_config_key,
        "current_value":     a.current_value,
        "approved_value":    a.approved_value,
        "approval_status":   a.approval_status,
        "rollback_key":      a.rollback_key,
        "approved_by":       a.approved_by,
        "approval_note":     a.approval_note,
    }


def _serialise_rollback_record(r: RollbackRecord) -> Dict[str, Any]:
    return {
        "receipt_id":        r.receipt_id,
        "action_id":         r.action_id,
        "target_config_key": r.target_config_key,
        "previous_value":    r.previous_value,
        "applied_value":     r.applied_value,
        "rollback_key":      r.rollback_key,
    }


def _serialise_receipt(receipt: ApplicationReceipt) -> Dict[str, Any]:
    return {
        "receipt_id":                  receipt.receipt_id,
        "schema_version":              receipt.schema_version,
        "source_manifest_id":          receipt.source_manifest_id,
        "source_reviewed_manifest_id": receipt.source_reviewed_manifest_id,
        "project_id":                  receipt.project_id,
        "config_path":                 receipt.config_path,
        "config_before_hash":          receipt.config_before_hash,
        "config_after_hash":           receipt.config_after_hash,
        "applied_actions":             receipt.applied_actions,
        "skipped_actions":             receipt.skipped_actions,
        "failed_actions":              receipt.failed_actions,
        "rollback_records":            [_serialise_rollback_record(r)
                                        for r in receipt.rollback_records],
        "rollback_ready":              receipt.rollback_ready,
    }


def _serialise_reviewed_manifest(rm: ReviewedManifest) -> Dict[str, Any]:
    return {
        "reviewed_manifest_id": rm.reviewed_manifest_id,
        "schema_version":       rm.schema_version,
        "source_manifest_id":   rm.source_manifest_id,
        "project_id":           rm.project_id,
        "approved_actions":     [_serialise_approved_action(a) for a in rm.approved_actions],
    }


# ---------------------------------------------------------------------------
# Public helper: load_manifest
# ---------------------------------------------------------------------------

def load_manifest(path: str) -> Any:
    """Load and validate a ConsumptionManifest JSON file from disk.

    Returns the raw dict (not a dataclass) because ConsumptionManifest is
    defined in controlled_consumption.py which Phase 16 must not import.
    The dict interface is used throughout Phase 16 for manifest data access.

    Raises ManifestApplicationError on missing, corrupt, or invalid files.
    """
    raw = _load_json_file(path)
    errors = _validate_manifest_integrity(raw)
    if errors:
        raise ManifestApplicationError(
            f"Manifest integrity check failed for {path!r}: {errors}"
        )
    return raw


# ---------------------------------------------------------------------------
# Public entry point 1: generate_reviewed_manifest
# ---------------------------------------------------------------------------

def generate_reviewed_manifest(
    manifest_path: str,
    approvals: Dict[str, Dict[str, Any]],
    results_dir: str,
) -> "ReviewedManifest":
    """Build a ReviewedManifest from a ConsumptionManifest and human approval decisions.

    The original manifest file is never mutated.
    The ReviewedManifest is written atomically under
    {results_dir}/.cache/reviewed_manifests/.

    Parameters
    ----------
    manifest_path:
        Path to the Phase 15 ConsumptionManifest JSON file.
    approvals:
        dict[action_id -> {"status": str, "approved_by": str, "note": str}]
        action_ids not present in approvals default to "pending".
        "status" must be "approved", "rejected", or "pending".
    results_dir:
        Root results directory; reviewed manifest written under .cache/ here.

    Returns
    -------
    ReviewedManifest — also persisted to disk.

    Raises
    ------
    ManifestApplicationError if manifest cannot be loaded or validated.
    """
    manifest = load_manifest(manifest_path)

    project_id = manifest.get("project_id", "unknown")
    source_manifest_id = manifest.get("manifest_id", "")

    approved_actions: List[ApprovedAction] = []

    for raw_action in manifest.get("generated_actions", []):
        action_id         = str(raw_action.get("action_id", ""))
        human_decision    = approvals.get(action_id, {})
        status            = str(human_decision.get("status", "pending"))
        if status not in _APPROVAL_STATUSES:
            status = "pending"

        approved_action = ApprovedAction(
            action_id         = action_id,
            proposal_id       = str(raw_action.get("proposal_id", "")),
            action_type       = str(raw_action.get("action_type", "")),
            target_config_key = str(raw_action.get("target_config_key", "")),
            current_value     = raw_action.get("current_value"),
            approved_value    = raw_action.get("suggested_value"),  # never substituted
            approval_status   = status,
            rollback_key      = str(raw_action.get("rollback_key",
                                                    raw_action.get("target_config_key", ""))),
            approved_by       = str(human_decision.get("approved_by", "")),
            approval_note     = str(human_decision.get("note", "")),
        )
        approved_actions.append(approved_action)

    # Sort by action_id for deterministic ordering.
    approved_actions.sort(key=lambda a: a.action_id)

    reviewed_manifest_id = _build_reviewed_manifest_id(source_manifest_id, approved_actions)

    reviewed = ReviewedManifest(
        reviewed_manifest_id = reviewed_manifest_id,
        schema_version       = _SCHEMA_VERSION,
        source_manifest_id   = source_manifest_id,
        project_id           = project_id,
        approved_actions     = approved_actions,
    )

    # Persist to .cache/reviewed_manifests/
    cache_dir = os.path.join(results_dir, ".cache", "reviewed_manifests")
    filename  = f"{project_id}_{reviewed_manifest_id}.json"
    path      = os.path.join(cache_dir, filename)
    _atomic_write_json(path, _serialise_reviewed_manifest(reviewed))
    logger.debug("manifest_application: reviewed manifest written to %s", path)

    return reviewed


# ---------------------------------------------------------------------------
# Internal application engine
# ---------------------------------------------------------------------------

def _apply_single_action(
    action: ApprovedAction,
    config_dict: Dict[str, Any],
    receipt_id: str,
) -> Tuple[Dict[str, Any], Optional[RollbackRecord], Optional[str]]:
    """Apply a single approved action to a config dict (in memory only).

    Returns (new_config_dict, rollback_record, error_string_or_None).
    On error, returns the original config_dict unchanged.
    Does NOT write to disk — the caller is responsible for atomic I/O.
    """
    # Re-validate action independently (defense in depth).
    errors = _validate_approved_action(action)
    if errors:
        return config_dict, None, "; ".join(errors)

    # Only apply approved actions.
    if action.approval_status != "approved":
        return config_dict, None, f"status is {action.approval_status!r}, not approved"

    # Unsupported action type: raise hard, not soft.
    if action.action_type not in _SUPPORTED_ACTION_TYPES:
        raise ManifestApplicationError(
            f"Unsupported action_type {action.action_type!r} encountered during application. "
            f"Only {sorted(_SUPPORTED_ACTION_TYPES)} are supported in v1."
        )

    # Capture previous_value from live config (not from Phase 15 generation time).
    previous_value = _get_dotted_value(config_dict, action.target_config_key)

    try:
        new_config = _set_dotted_key(config_dict, action.target_config_key, action.approved_value)
    except ManifestApplicationError as exc:
        return config_dict, None, str(exc)

    rollback = RollbackRecord(
        receipt_id        = receipt_id,
        action_id         = action.action_id,
        target_config_key = action.target_config_key,
        previous_value    = previous_value,
        applied_value     = action.approved_value,
        rollback_key      = action.rollback_key,
    )
    return new_config, rollback, None


# ---------------------------------------------------------------------------
# Public entry point 2: apply_manifest
# ---------------------------------------------------------------------------

def apply_manifest(
    reviewed_manifest_path: str,
    manifest_path: str,
    config_path: str,
    results_dir: str,
) -> "ApplicationReceipt":
    """Apply approved actions from a ReviewedManifest to a config file.

    Critical ordering (enforced explicitly in code):
    1. Load current config from disk.
    2. Validate reviewed manifest and original manifest.
    3. For each approved action: compute patch in memory, capture previous_value.
    4. Build rollback records and receipt payload.
    5. Write receipt artifact to .cache FIRST (atomically).
    6. Only then write patched config (atomically).

    This guarantees that rollback data always exists before the config is committed.

    Parameters
    ----------
    reviewed_manifest_path:
        Path to the ReviewedManifest JSON file produced by generate_reviewed_manifest().
    manifest_path:
        Path to the original ConsumptionManifest JSON file (for cross-check).
    config_path:
        Absolute path to the config JSON file to be patched (e.g. config/config.json).
    results_dir:
        Root results directory for receipt output under .cache/.

    Returns
    -------
    ApplicationReceipt — also persisted to disk.

    Raises
    ------
    ManifestApplicationError for structural failures (corrupt files, unsupported
    action types, conflicting manifest ids). Partial failures per-action are
    recorded in the receipt as failed_actions, not raised.
    """
    # --- Step 1: Load and validate all inputs ---

    # Load reviewed manifest
    reviewed_raw = _load_json_file(reviewed_manifest_path)
    rev_errors = _validate_manifest_integrity({
        "schema_version":    reviewed_raw.get("schema_version"),
        "manifest_id":       reviewed_raw.get("reviewed_manifest_id", "__reviewed__"),
        "project_id":        reviewed_raw.get("project_id"),
        "generated_actions": reviewed_raw.get("approved_actions", []),
    })
    if rev_errors:
        raise ManifestApplicationError(
            f"ReviewedManifest integrity check failed: {rev_errors}"
        )

    reviewed_manifest_id = reviewed_raw.get("reviewed_manifest_id", "")
    source_manifest_id   = reviewed_raw.get("source_manifest_id", "")
    project_id           = reviewed_raw.get("project_id", "unknown")

    # Cross-check: source manifest ids must match
    original_manifest = load_manifest(manifest_path)
    if original_manifest.get("manifest_id") != source_manifest_id:
        raise ManifestApplicationError(
            f"ReviewedManifest.source_manifest_id {source_manifest_id!r} does not match "
            f"ConsumptionManifest.manifest_id {original_manifest.get('manifest_id')!r}"
        )

    # Load current config
    live_config = _load_json_file(config_path)
    if not isinstance(live_config, dict):
        raise ManifestApplicationError(
            f"Config file {config_path!r} does not contain a JSON object"
        )

    config_before_hash = _hash_config(live_config)

    # --- Step 2: Process actions in deterministic order ---

    approved_action_dicts = reviewed_raw.get("approved_actions", [])
    # Sort by action_id for deterministic application order.
    approved_action_dicts = sorted(approved_action_dicts, key=lambda a: a.get("action_id", ""))

    applied_ids:  List[str] = []
    skipped_ids:  List[str] = []
    failed_ids:   List[str] = []
    rollback_records: List[RollbackRecord] = []

    current_config = live_config  # evolves as each action is applied in memory

    for raw in approved_action_dicts:
        action = ApprovedAction(
            action_id         = str(raw.get("action_id", "")),
            proposal_id       = str(raw.get("proposal_id", "")),
            action_type       = str(raw.get("action_type", "")),
            target_config_key = str(raw.get("target_config_key", "")),
            current_value     = raw.get("current_value"),
            approved_value    = raw.get("approved_value"),
            approval_status   = str(raw.get("approval_status", "pending")),
            rollback_key      = str(raw.get("rollback_key",
                                            raw.get("target_config_key", ""))),
            approved_by       = str(raw.get("approved_by", "")),
            approval_note     = str(raw.get("approval_note", "")),
        )

        status = action.approval_status
        if status != "approved":
            skipped_ids.append(action.action_id)
            logger.debug(
                "manifest_application: skipping action %s (status=%s)",
                action.action_id, status,
            )
            continue

        # Hard check: unsupported action_type must raise, never silently skip.
        if action.action_type not in _SUPPORTED_ACTION_TYPES:
            raise ManifestApplicationError(
                f"Unsupported action_type {action.action_type!r} for action "
                f"{action.action_id!r}. Only {sorted(_SUPPORTED_ACTION_TYPES)} "
                "are supported in v1."
            )

        # Placeholder receipt_id used here; real one computed after all actions.
        # RollbackRecord uses "pending_receipt" until receipt_id is finalised.
        new_config, rollback, error = _apply_single_action(action, current_config, "pending")
        if error:
            failed_ids.append(action.action_id)
            logger.debug(
                "manifest_application: action %s failed: %s", action.action_id, error
            )
        else:
            applied_ids.append(action.action_id)
            if rollback:
                rollback_records.append(rollback)
            current_config = new_config

    # --- Step 3: Compute final hashes and ids ---

    config_after_hash = _hash_config(current_config)

    receipt_id = _build_receipt_id(source_manifest_id, reviewed_manifest_id, applied_ids)

    # Patch receipt_id into rollback records now that it's known.
    for r in rollback_records:
        r.receipt_id = receipt_id

    rollback_ready = len(rollback_records) == len(applied_ids)

    receipt = ApplicationReceipt(
        receipt_id                  = receipt_id,
        schema_version              = _SCHEMA_VERSION,
        source_manifest_id          = source_manifest_id,
        source_reviewed_manifest_id = reviewed_manifest_id,
        project_id                  = project_id,
        config_path                 = os.path.abspath(config_path),
        config_before_hash          = config_before_hash,
        config_after_hash           = config_after_hash,
        applied_actions             = applied_ids,
        skipped_actions             = skipped_ids,
        failed_actions              = failed_ids,
        rollback_records            = rollback_records,
        rollback_ready              = rollback_ready,
    )

    # --- Steps 5 & 6: Write receipt FIRST, then config (critical ordering) ---

    # Step 5: Persist receipt artifact atomically BEFORE touching config.
    receipt_cache_dir = os.path.join(results_dir, ".cache", "application_receipts")
    receipt_filename  = f"{project_id}_{receipt_id}.json"
    receipt_path      = os.path.join(receipt_cache_dir, receipt_filename)
    _atomic_write_json(receipt_path, _serialise_receipt(receipt))
    logger.debug("manifest_application: receipt written to %s", receipt_path)

    # Step 6: Only NOW replace the config file (atomic).
    if applied_ids:
        _atomic_write_json(config_path, current_config)
        logger.debug(
            "manifest_application: config patched at %s (%d action(s) applied)",
            config_path, len(applied_ids),
        )
    else:
        logger.debug(
            "manifest_application: no approved actions applied — config unchanged"
        )

    logger.debug(
        "manifest_application: receipt=%s applied=%d skipped=%d failed=%d",
        receipt_id, len(applied_ids), len(skipped_ids), len(failed_ids),
    )
    return receipt


# ---------------------------------------------------------------------------
# Public entry point 3: rollback_application
# ---------------------------------------------------------------------------

def rollback_application(receipt_path: str, config_path: str) -> None:
    """Revert all applied actions recorded in an ApplicationReceipt.

    Uses RollbackRecord.previous_value (captured from live config at application
    time) — NOT ConsumableAction.current_value from Phase 15 generation time.

    Actions are reverted in reverse application order (last applied, first reverted).
    Config write is atomic. The receipt file is NOT deleted after rollback.

    Parameters
    ----------
    receipt_path:
        Path to the ApplicationReceipt JSON file.
    config_path:
        Path to the config JSON file to revert.

    Raises
    ------
    ManifestApplicationError if the receipt or config cannot be loaded,
    or if the receipt contains no rollback records.
    """
    receipt_raw = _load_json_file(receipt_path)
    if not isinstance(receipt_raw, dict):
        raise ManifestApplicationError(
            f"Receipt at {receipt_path!r} is not a JSON object"
        )

    rollback_records_raw = receipt_raw.get("rollback_records", [])
    if not rollback_records_raw:
        logger.debug(
            "manifest_application: no rollback_records in receipt %s — nothing to revert",
            receipt_path,
        )
        return

    # Load current config.
    config = _load_json_file(config_path)
    if not isinstance(config, dict):
        raise ManifestApplicationError(
            f"Config at {config_path!r} is not a JSON object"
        )

    # Apply rollbacks in reverse order (last applied = first reverted).
    for record_raw in reversed(rollback_records_raw):
        key            = str(record_raw.get("target_config_key", ""))
        previous_value = record_raw.get("previous_value")
        action_id      = str(record_raw.get("action_id", ""))

        if not key:
            logger.debug(
                "manifest_application: skipping rollback record with empty key "
                "(action_id=%s)", action_id
            )
            continue

        try:
            config = _set_dotted_key(config, key, previous_value)
            logger.debug(
                "manifest_application: rolled back %s = %r (action %s)",
                key, previous_value, action_id,
            )
        except ManifestApplicationError as exc:
            logger.debug(
                "manifest_application: rollback failed for %s: %s", key, exc
            )
            raise

    # Write reverted config atomically.
    _atomic_write_json(config_path, config)
    logger.debug(
        "manifest_application: rollback complete, config restored at %s", config_path
    )
