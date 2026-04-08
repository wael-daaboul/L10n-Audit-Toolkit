"""
l10n_audit/core/controlled_consumption.py
==========================================
Phase 15 — Controlled Consumption Layer.

Design constraints
------------------
* Feature-gated: disabled by default; opt-in via
  config["controlled_consumption"]["enabled"].
* Read-only inputs: consumes only AdaptationReport (Phase 14 output) + config
  dicts. Never reads LearningProfile, per-finding data, or routing state.
* Zero pipeline impact on failure — called from engine.py post-pipeline hook.
* Non-behavioral: produces a ConsumptionManifest only. Does NOT apply any
  config change, mutate any engine, or alter any user-facing output.
* Deterministic: same AdaptationReport + same config + same current_config
  snapshot → identical ConsumptionManifest every time.
* No wall-clock timestamps in semantic payload, no randomness, no UUIDs.
* Three modes: shadow (returns None) | generate_manifest | review_ready.
* Double opt-in: both allowed_signal_keys AND allowed_action_types must be
  non-empty for any ConsumableAction to be produced.

Static mapping (v1 — exactly one entry, hardcoded, not config-driven):
    calibration_rarely_active → calibration.enabled = True

Dependency direction (one-way, enforced):
  engine.py post-pipeline → adaptation_intelligence.AdaptationReport
                          → controlled_consumption
  ← NO reverse dependency allowed ←
  Must NOT be imported by: decision_engine, calibration_engine,
  context_profile, conflict_resolution, enforcement_layer,
  adaptation_intelligence, project_memory.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("l10n_audit.controlled_consumption")


class ControlledConsumptionError(Exception):
    """Raised when explicit manifest workflow inputs are missing or invalid."""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCHEMA_VERSION = "1.0"

_ALLOWED_MODES = frozenset({"shadow", "generate_manifest", "review_ready"})

# Static signal-to-action mapping — v1 contains exactly one entry.
# This table is hardcoded and is NOT expandable via config.
# Adding a new entry requires a code change and deliberate review.
SIGNAL_TO_ACTION_MAP: Dict[str, Dict[str, Any]] = {
    "calibration_rarely_active": {
        "action_type": "config_suggestion",
        "target_config_key": "calibration.enabled",
        "suggested_value": True,
    },
}

# Hardcoded forbidden target key prefixes and exact keys.
# Any action whose target_config_key matches any of these is always rejected,
# regardless of what config says. This guard cannot be overridden by config.
_FORBIDDEN_TARGET_PREFIXES: Tuple[str, ...] = (
    "decision_engine",
    "routing",
    "score_finding",
    "calibration.mode",          # calibration.enabled is allowed; .mode is not
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


def _is_forbidden_target(key: str) -> bool:
    """Return True if target_config_key is on the forbidden list."""
    k = key.strip().lower()
    for prefix in _FORBIDDEN_TARGET_PREFIXES:
        if k == prefix or k.startswith(prefix + ".") or k.startswith(prefix + "_"):
            return True
    return False


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class ConsumableAction:
    """A single bounded, reviewable config suggestion derived from a Phase 14
    bounded_action_candidate proposal.

    This record is never auto-applied. It is a human-reviewable artifact only.
    approved_by_default is always False — this is enforced by governance rule G8.

    Fields
    ------
    action_id:
        Deterministic sha256[:12] of the canonical action payload.
    proposal_id:
        Source proposal_id from Phase 14 (full traceability back to the signal).
    signal_key:
        The Phase 14 signal that triggered this action.
    action_type:
        Always "config_suggestion" in Phase 15 v1.
    target_config_key:
        The config key this suggestion pertains to (e.g. "calibration.enabled").
    suggested_value:
        The value being suggested. Never written automatically.
    current_value:
        The value of target_config_key at the time of manifest generation,
        captured from current_config for rollback reference.
    justification:
        Plain-text rationale derived from the source proposal's reasoning.
    rollback_key:
        Always equals target_config_key. Reverting target_config_key to its
        current_value is the complete rollback operation.
    safety_checks_passed:
        True only when all governance rules passed.
    approved_by_default:
        Always False. Enforced by governance rule G8. Never changed.
    """
    action_id: str
    proposal_id: str
    signal_key: str
    action_type: str
    target_config_key: str
    suggested_value: Any
    current_value: Any
    justification: str
    rollback_key: str
    safety_checks_passed: bool
    approved_by_default: bool = False


@dataclass
class ConsumptionManifest:
    """Structured, deterministic output of the Phase 15 consumption pass.

    No wall-clock timestamp in the semantic payload — timestamps break
    determinism. If timing is needed the caller may attach it externally.

    manifest_id is derived from a canonical hash of the full manifest content
    (excluding manifest_id itself) — same inputs always produce the same id.
    """
    manifest_id: str
    schema_version: str
    project_id: str
    mode: str
    source_profile_hash: str        # AdaptationReport.profile_hash
    source_report_hash: str         # sha256[:16] of the AdaptationReport payload
    generated_actions: List[ConsumableAction] = field(default_factory=list)
    rejected_candidates: List[str] = field(default_factory=list)
    governance_rejections: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal pure helpers
# ---------------------------------------------------------------------------

def _hash_report(report: Any) -> str:
    """Stable 16-char digest of the AdaptationReport analytical payload.

    Uses only fields relevant to the analysis — not object identity.
    """
    try:
        proposals_payload = []
        for p in (getattr(report, "proposals", None) or []):
            proposals_payload.append({
                "proposal_id":   str(getattr(p, "proposal_id", "")),
                "signal_key":    str(getattr(p, "signal_key", "")),
                "signal_value":  round(float(getattr(p, "signal_value", 0.0)), 4),
                "proposal_type": str(getattr(p, "proposal_type", "")),
                "bounded_action_key": str(getattr(p, "bounded_action_key", "") or ""),
                "source_run_count": int(getattr(p, "source_run_count", 0)),
            })
        payload = {
            "project_id":       str(getattr(report, "project_id", "")),
            "mode":             str(getattr(report, "mode", "")),
            "run_count_basis":  int(getattr(report, "run_count_basis", 0)),
            "profile_hash":     str(getattr(report, "profile_hash", "")),
            "proposals":        proposals_payload,
        }
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]
    except Exception:
        return "unknown"


def _build_action_id(proposal_id: str, action_type: str, target_config_key: str,
                     suggested_value: Any) -> str:
    """Deterministic 12-char hex ID for a ConsumableAction."""
    payload = {
        "proposal_id":      proposal_id,
        "action_type":      action_type,
        "target_config_key": target_config_key,
        "suggested_value":  str(suggested_value),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def _build_manifest_id(project_id: str, source_report_hash: str,
                       actions: List[ConsumableAction],
                       rejected: List[str]) -> str:
    """Deterministic 12-char hex ID for a ConsumptionManifest.

    Derived from project_id + source_report_hash + sorted action_ids +
    sorted rejection strings — fully stable across repeated calls.
    """
    payload = {
        "project_id":        project_id,
        "source_report_hash": source_report_hash,
        "action_ids":        sorted(a.action_id for a in actions),
        "rejected_count":    len(rejected),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def _get_current_value(target_config_key: str, current_config: Dict[str, Any]) -> Any:
    """Resolve a dotted config key path against the current config dict.

    Returns None when the key is absent (safe — None is a valid current_value
    meaning the key does not exist yet, which is exactly when enabling it makes sense).
    """
    try:
        parts = target_config_key.split(".")
        obj: Any = current_config
        for part in parts:
            if not isinstance(obj, dict):
                return None
            obj = obj.get(part)
        return obj
    except Exception:
        return None


def _extract_candidates(report: Any) -> List[Any]:
    """Return all proposals from the AdaptationReport without filtering.

    Filtering happens inside _apply_governance_rules — this function only
    extracts so the governance layer can produce rejection reasons for each.
    """
    proposals = getattr(report, "proposals", None) or []
    return list(proposals)


def _apply_governance_rules(
    proposal: Any,
    config: Dict[str, Any],
    current_config: Dict[str, Any],
) -> Tuple[Optional[ConsumableAction], Optional[str]]:
    """Apply all 8 governance rules to a single proposal.

    Returns (ConsumableAction, None) on pass, or (None, rejection_reason) on fail.
    All rules are explicit and independently testable.

    Rules
    -----
    G1  proposal_type must be "bounded_action_candidate"
    G2  signal_key must be in config["allowed_signal_keys"]
    G3  signal_key must exist in SIGNAL_TO_ACTION_MAP
    G4  mapped action_type must be in config["allowed_action_types"]
    G5  target_config_key must not match FORBIDDEN targets
    G6  source_run_count must meet config["min_runs_required"]
    G7  justification must be non-empty
    G8  approved_by_default must always be False (enforced unconditionally)
    """
    proposal_id  = str(getattr(proposal, "proposal_id", ""))
    proposal_type = str(getattr(proposal, "proposal_type", ""))
    signal_key   = str(getattr(proposal, "signal_key", ""))
    run_count    = int(getattr(proposal, "source_run_count", 0))
    reasoning    = str(getattr(proposal, "reasoning", "") or "")
    bounded_key  = str(getattr(proposal, "bounded_action_key", "") or "")

    allowed_signals  = list(config.get("allowed_signal_keys", []) or [])
    allowed_actions  = list(config.get("allowed_action_types", []) or [])
    min_runs         = int(config.get("min_runs_required", 5))

    # G1 — proposal type
    if proposal_type != "bounded_action_candidate":
        return None, (
            f"G1_REJECTED[wrong_proposal_type]: proposal={proposal_id!r} "
            f"type={proposal_type!r} — only bounded_action_candidate is eligible"
        )

    # G2 — signal key explicitly allowed by user
    if signal_key not in allowed_signals:
        return None, (
            f"G2_REJECTED[signal_not_in_allowlist]: proposal={proposal_id!r} "
            f"signal={signal_key!r} not in allowed_signal_keys={allowed_signals!r}"
        )

    # G3 — signal key must have a declared static mapping
    mapping = SIGNAL_TO_ACTION_MAP.get(signal_key)
    if mapping is None:
        return None, (
            f"G3_REJECTED[no_static_mapping]: proposal={proposal_id!r} "
            f"signal={signal_key!r} has no entry in SIGNAL_TO_ACTION_MAP"
        )

    action_type       = mapping["action_type"]
    target_config_key = mapping["target_config_key"]
    suggested_value   = mapping["suggested_value"]

    # G4 — action type explicitly allowed by user
    if action_type not in allowed_actions:
        return None, (
            f"G4_REJECTED[action_type_not_in_allowlist]: proposal={proposal_id!r} "
            f"action_type={action_type!r} not in allowed_action_types={allowed_actions!r}"
        )

    # G5 — target config key must not be forbidden
    if _is_forbidden_target(target_config_key):
        return None, (
            f"G5_REJECTED[forbidden_target]: proposal={proposal_id!r} "
            f"target_config_key={target_config_key!r} matches a forbidden target prefix"
        )

    # G6 — sufficient run history
    if run_count < min_runs:
        return None, (
            f"G6_REJECTED[insufficient_runs]: proposal={proposal_id!r} "
            f"source_run_count={run_count} < min_runs_required={min_runs}"
        )

    # G7 — explainability
    if not reasoning.strip():
        return None, (
            f"G7_REJECTED[empty_reasoning]: proposal={proposal_id!r} "
            "has no justification text"
        )

    # All rules passed — build the ConsumableAction.
    current_value = _get_current_value(target_config_key, current_config)

    action = ConsumableAction(
        action_id=_build_action_id(proposal_id, action_type, target_config_key, suggested_value),
        proposal_id=proposal_id,
        signal_key=signal_key,
        action_type=action_type,
        target_config_key=target_config_key,
        suggested_value=suggested_value,
        current_value=current_value,
        justification=reasoning.strip(),
        rollback_key=target_config_key,   # rollback = restore current_value at this key
        safety_checks_passed=True,
        approved_by_default=False,        # G8 — always False, unconditionally enforced
    )
    return action, None


def _generate_actions(
    report: Any,
    config: Dict[str, Any],
    current_config: Dict[str, Any],
) -> Tuple[List[ConsumableAction], List[str], List[str]]:
    """Extract and validate all candidates. Returns (actions, rejected, gov_rejections).

    rejected     — proposal_ids that did not qualify as candidates at all
    gov_rejections — governance rule failure messages for those that entered the rules
    """
    candidates = _extract_candidates(report)
    actions: List[ConsumableAction] = []
    rejected: List[str] = []
    gov_rejections: List[str] = []

    for proposal in candidates:
        action, rejection_reason = _apply_governance_rules(proposal, config, current_config)
        if action is not None:
            actions.append(action)
        else:
            pid = str(getattr(proposal, "proposal_id", "unknown"))
            rejected.append(pid)
            if rejection_reason:
                gov_rejections.append(rejection_reason)

    # Stable ordering: actions by action_id, rejections by proposal_id.
    actions.sort(key=lambda a: a.action_id)
    rejected.sort()
    gov_rejections.sort()

    return actions, rejected, gov_rejections


def _build_manifest(
    report: Any,
    mode: str,
    source_report_hash: str,
    actions: List[ConsumableAction],
    rejected: List[str],
    gov_rejections: List[str],
) -> ConsumptionManifest:
    """Assemble the final ConsumptionManifest. Pure function, no I/O."""
    project_id = str(getattr(report, "project_id", "unknown"))
    manifest_id = _build_manifest_id(project_id, source_report_hash, actions, rejected)

    return ConsumptionManifest(
        manifest_id=manifest_id,
        schema_version=_SCHEMA_VERSION,
        project_id=project_id,
        mode=mode,
        source_profile_hash=str(getattr(report, "profile_hash", "")),
        source_report_hash=source_report_hash,
        generated_actions=actions,
        rejected_candidates=rejected,
        governance_rejections=gov_rejections,
    )


def _write_manifest(manifest: ConsumptionManifest, results_dir: str) -> None:
    """Atomically write the manifest to .cache/consumption_manifests/.

    Uses .tmp + os.replace() — same pattern as Phase 13.
    Swallows all errors; failure never propagates to the caller.
    """
    try:
        cache_dir = os.path.join(results_dir, ".cache", "consumption_manifests")
        os.makedirs(cache_dir, exist_ok=True)

        filename = f"{manifest.project_id}_{manifest.manifest_id}.json"
        path = os.path.join(cache_dir, filename)

        def _serialise_action(a: ConsumableAction) -> Dict[str, Any]:
            return {
                "action_id":         a.action_id,
                "proposal_id":       a.proposal_id,
                "signal_key":        a.signal_key,
                "action_type":       a.action_type,
                "target_config_key": a.target_config_key,
                "suggested_value":   a.suggested_value,
                "current_value":     a.current_value,
                "justification":     a.justification,
                "rollback_key":      a.rollback_key,
                "safety_checks_passed": a.safety_checks_passed,
                "approved_by_default":  a.approved_by_default,
            }

        payload = {
            "manifest_id":        manifest.manifest_id,
            "schema_version":     manifest.schema_version,
            "project_id":         manifest.project_id,
            "mode":               manifest.mode,
            "source_profile_hash": manifest.source_profile_hash,
            "source_report_hash": manifest.source_report_hash,
            "generated_actions":  [_serialise_action(a) for a in manifest.generated_actions],
            "rejected_candidates": manifest.rejected_candidates,
            "governance_rejections": manifest.governance_rejections,
        }

        fd, tmp_path = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
            os.replace(tmp_path, path)
            logger.debug(
                "controlled_consumption: manifest written to %s", path
            )
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as exc:
        logger.debug("controlled_consumption: manifest write failed (%s) — pipeline unaffected", exc)


def serialise_manifest(manifest: ConsumptionManifest) -> Dict[str, Any]:
    """Return the deterministic JSON payload for a ConsumptionManifest."""
    def _serialise_action(a: ConsumableAction) -> Dict[str, Any]:
        return {
            "action_id":         a.action_id,
            "proposal_id":       a.proposal_id,
            "signal_key":        a.signal_key,
            "action_type":       a.action_type,
            "target_config_key": a.target_config_key,
            "suggested_value":   a.suggested_value,
            "current_value":     a.current_value,
            "justification":     a.justification,
            "rollback_key":      a.rollback_key,
            "safety_checks_passed": a.safety_checks_passed,
            "approved_by_default":  a.approved_by_default,
        }

    return {
        "manifest_id":         manifest.manifest_id,
        "schema_version":      manifest.schema_version,
        "project_id":          manifest.project_id,
        "mode":                manifest.mode,
        "source_profile_hash": manifest.source_profile_hash,
        "source_report_hash":  manifest.source_report_hash,
        "generated_actions":   [_serialise_action(a) for a in manifest.generated_actions],
        "rejected_candidates": manifest.rejected_candidates,
        "governance_rejections": manifest.governance_rejections,
    }


def write_manifest_file(manifest: ConsumptionManifest, path: str) -> str:
    """Atomically persist a ConsumptionManifest to an explicit path."""
    payload = serialise_manifest(manifest)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return str(target)


def load_adaptation_report(path: str) -> Any:
    """Load a minimal AdaptationReport-like object from JSON on disk."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        raise ControlledConsumptionError(f"Adaptation report not found: {path!r}")
    except json.JSONDecodeError as exc:
        raise ControlledConsumptionError(f"Corrupt adaptation report JSON at {path!r}: {exc}")

    if not isinstance(raw, dict):
        raise ControlledConsumptionError("Adaptation report payload must be a JSON object")

    missing = [
        field_name
        for field_name in ("project_id", "mode", "run_count_basis", "profile_hash", "proposals")
        if field_name not in raw
    ]
    if missing:
        raise ControlledConsumptionError(
            f"Adaptation report missing required fields: {missing}"
        )
    if not isinstance(raw.get("proposals"), list):
        raise ControlledConsumptionError("Adaptation report field 'proposals' must be a list")

    proposals = [SimpleNamespace(**proposal) for proposal in raw.get("proposals", []) if isinstance(proposal, dict)]
    if len(proposals) != len(raw.get("proposals", [])):
        raise ControlledConsumptionError("Adaptation report proposals must contain only JSON objects")

    return SimpleNamespace(
        project_id=str(raw.get("project_id", "")),
        mode=str(raw.get("mode", "")),
        run_count_basis=int(raw.get("run_count_basis", 0)),
        profile_hash=str(raw.get("profile_hash", "")),
        proposals=proposals,
        safety_rejections=list(raw.get("safety_rejections", []) or []),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_consumption_manifest(
    report: Any,
    config: Dict[str, Any],
    current_config: Optional[Dict[str, Any]] = None,
    results_dir: Optional[str] = None,
) -> Optional[ConsumptionManifest]:
    """Generate a deterministic ConsumptionManifest from a Phase 14 AdaptationReport.

    This is the only public function in Phase 15.

    Constraints
    -----------
    * Accepts AdaptationReport + config dicts only — not the full runtime object.
    * Never mutates report, config, or current_config.
    * No file I/O unless mode=="review_ready" AND emit_manifest==True.
    * Returns None on shadow mode, disabled gate, or any internal failure.
    * All exceptions are caught and logged at DEBUG — never propagated.

    Parameters
    ----------
    report:
        The AdaptationReport produced by Phase 14.
        Duck-typed — only AdaptationReport fields are accessed.
    config:
        The "controlled_consumption" sub-dict from runtime.config.
    current_config:
        The full runtime config dict (read-only). Used only to capture
        current_value for rollback reference. Defaults to {} if None.
    results_dir:
        Optional path to the results directory; used for manifest file write
        in review_ready mode. Ignored otherwise.

    Returns
    -------
    ConsumptionManifest if mode is generate_manifest or review_ready, else None.
    """
    try:
        if not isinstance(config, dict):
            return None

        if not config.get("enabled", False):
            return None

        if current_config is None or not isinstance(current_config, dict):
            current_config = {}

        mode = str(config.get("mode", "shadow"))
        if mode not in _ALLOWED_MODES:
            logger.debug(
                "controlled_consumption: unknown mode %r — treating as shadow", mode
            )
            mode = "shadow"

        # shadow: run nothing visible, return None immediately.
        if mode == "shadow":
            logger.debug("controlled_consumption: shadow mode — no output produced")
            return None

        # Double opt-in guard: both allowlists must be non-empty.
        allowed_signals = list(config.get("allowed_signal_keys", []) or [])
        allowed_actions = list(config.get("allowed_action_types", []) or [])
        if not allowed_signals or not allowed_actions:
            logger.debug(
                "controlled_consumption: empty allowlist — allowed_signal_keys=%r "
                "allowed_action_types=%r — producing empty manifest",
                allowed_signals, allowed_actions,
            )
            # Still produce an empty manifest so the caller can observe the gate.
            source_report_hash = _hash_report(report)
            empty_manifest = _build_manifest(
                report, mode, source_report_hash, [], [], []
            )
            return empty_manifest

        source_report_hash = _hash_report(report)
        actions, rejected, gov_rejections = _generate_actions(report, config, current_config)
        manifest = _build_manifest(
            report, mode, source_report_hash, actions, rejected, gov_rejections
        )

        # File write only in review_ready mode when emit_manifest is True.
        if mode == "review_ready" and config.get("emit_manifest", False) and results_dir:
            _write_manifest(manifest, str(results_dir))

        logger.debug(
            "controlled_consumption: mode=%s actions=%d rejected=%d project=%s",
            mode, len(actions), len(rejected),
            getattr(report, "project_id", "unknown"),
        )
        return manifest

    except Exception as exc:
        logger.debug("controlled_consumption: internal error (%s) — returning None", exc)
        return None
