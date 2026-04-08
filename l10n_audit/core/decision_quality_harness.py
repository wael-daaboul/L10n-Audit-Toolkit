from __future__ import annotations

from typing import Any


ROUTE_ORDER = ("auto_fix", "ai_review", "manual_review", "dropped", "unknown")
CONFIDENCE_BAND_ORDER = ("high_confidence", "medium_confidence", "low_confidence")


def _empty_route_distribution() -> dict[str, int]:
    return {route: 0 for route in ROUTE_ORDER}


def _empty_confidence_bands() -> dict[str, int]:
    return {band: 0 for band in CONFIDENCE_BAND_ORDER}


def _read_explanation(finding: Any) -> dict[str, Any]:
    explanation = getattr(finding, "_decision_explanation", {})
    return explanation if isinstance(explanation, dict) else {}


def _extract_route(explanation: dict[str, Any]) -> str:
    route = str(explanation.get("route_after_context", "")).strip().lower()
    return route if route in ROUTE_ORDER else "unknown"


def _extract_confidence(finding: Any, explanation: dict[str, Any]) -> float:
    raw = getattr(finding, "confidence_score", explanation.get("final_confidence", 0.0))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _confidence_band(confidence: float) -> str:
    if confidence >= 0.8:
        return "high_confidence"
    if confidence <= 0.3:
        return "low_confidence"
    return "medium_confidence"


def _sorted_source_dict(source_map: dict[str, dict[str, float | int]]) -> dict[str, dict[str, float | int]]:
    return {source: source_map[source] for source in sorted(source_map)}


def _validate_decision_quality_shape(summary: dict) -> None:
    from l10n_audit.contracts.decision_quality_contract import DECISION_QUALITY_CONTRACT

    for key, expected_type in DECISION_QUALITY_CONTRACT.items():
        if key not in summary:
            raise ValueError(f"Missing decision quality key: {key}")
        if not isinstance(summary[key], expected_type):
            raise TypeError(f"{key} must be of type {expected_type}")


def evaluate_decision_quality(findings: list[Any]) -> dict[str, Any]:
    route_distribution = _empty_route_distribution()
    confidence_bands = _empty_confidence_bands()
    evidence_source_usage: dict[str, int] = {}
    contribution_impact_summary: dict[str, dict[str, float | int]] = {}
    quality_risk_indicators = {
        "low_confidence_auto_fix_count": 0,
        "high_confidence_manual_review_count": 0,
        "semantic_penalty_cases": 0,
        "cross_evidence_cases": 0,
        "profile_weighted_cases": 0,
        "missing_explanation_count": 0,
    }

    semantic_codes = {
        "meaning_loss_high_penalty",
        "meaning_loss_medium_penalty",
        "semantic_shape_mismatch_penalty",
        "semantic_action_loss_penalty",
        "semantic_entity_mismatch_penalty",
    }

    for finding in findings:
        explanation = _read_explanation(finding)
        if not explanation:
            quality_risk_indicators["missing_explanation_count"] += 1
            route_distribution["unknown"] += 1
            confidence = _extract_confidence(finding, explanation)
            confidence_bands[_confidence_band(confidence)] += 1
            continue

        route = _extract_route(explanation)
        confidence = _extract_confidence(finding, explanation)
        route_distribution[route] += 1
        confidence_bands[_confidence_band(confidence)] += 1

        evidence_sources = explanation.get("evidence_sources", [])
        if isinstance(evidence_sources, list):
            for source in evidence_sources:
                source_name = str(source)
                evidence_source_usage[source_name] = evidence_source_usage.get(source_name, 0) + 1

        score_factors = explanation.get("score_factors", [])
        if isinstance(score_factors, list):
            for factor in score_factors:
                if not isinstance(factor, dict):
                    continue
                source = str(factor.get("source", "unknown"))
                delta = float(factor.get("delta", 0.0))
                kind = str(factor.get("kind", "penalty" if delta < 0 else "bonus"))
                bucket = contribution_impact_summary.setdefault(
                    source,
                    {
                        "source_total_delta": 0.0,
                        "source_count": 0,
                        "penalty_count": 0,
                        "bonus_count": 0,
                    },
                )
                bucket["source_total_delta"] = round(float(bucket["source_total_delta"]) + delta, 6)
                bucket["source_count"] = int(bucket["source_count"]) + 1
                if kind == "penalty":
                    bucket["penalty_count"] = int(bucket["penalty_count"]) + 1
                else:
                    bucket["bonus_count"] = int(bucket["bonus_count"]) + 1

        explanation_codes = explanation.get("explanation_codes", [])
        if not isinstance(explanation_codes, list):
            explanation_codes = []

        if route == "auto_fix" and confidence < 0.8:
            quality_risk_indicators["low_confidence_auto_fix_count"] += 1
        if route == "manual_review" and confidence > 0.3:
            quality_risk_indicators["high_confidence_manual_review_count"] += 1
        if any(code in semantic_codes for code in explanation_codes):
            quality_risk_indicators["semantic_penalty_cases"] += 1
        if "cross_evidence" in evidence_sources:
            quality_risk_indicators["cross_evidence_cases"] += 1
        if "context_profile_weighting" in evidence_sources:
            quality_risk_indicators["profile_weighted_cases"] += 1

    summary = {
        "total_findings": len(findings),
        "route_distribution": route_distribution,
        "confidence_bands": confidence_bands,
        "evidence_source_usage": {source: evidence_source_usage[source] for source in sorted(evidence_source_usage)},
        "quality_risk_indicators": quality_risk_indicators,
        "contribution_impact_summary": _sorted_source_dict(contribution_impact_summary),
    }
    _validate_decision_quality_shape(summary)
    return summary
