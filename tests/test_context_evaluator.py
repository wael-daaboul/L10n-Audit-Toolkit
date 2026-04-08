from l10n_audit.core.context_evaluator import (
    build_context_bundle,
    evaluate_candidate_change,
    infer_text_type,
    semantic_similarity,
)


def test_context_bundle_blocks_sentence_collapse_into_entity_label() -> None:
    bundle = build_context_bundle(
        "add_vehicle_details",
        "Add vehicle details to send approval request to admin.",
        "أضف بيانات المركبة لإرسال طلب الموافقة إلى الإدارة.",
        usage_locations=["helper_text"],
        usage_metadata={
            "ui_surfaces": ["form"],
            "text_roles": ["message"],
            "action_hints": ["action"],
            "audience_hints": ["role_specific"],
            "sentence_shapes": ["sentence_like"],
        },
        linguistic_signals={"lt_grammar_flags": 1, "lt_style_flags": 0, "lt_literalness_support": False, "sources": ["languagetool"]},
        role_identifiers=["المدير"],
        entity_whitelist={"en": ["admin"], "ar": ["الإدارة"]},
    )

    decision = evaluate_candidate_change(
        bundle, "المدير", role_identifiers=["المدير"], entity_whitelist={"en": ["admin"], "ar": ["الإدارة"]}
    )

    assert bundle["inferred_text_type"] == "helper_text"
    assert bundle["ui_surface"] == "form"
    assert bundle["text_role"] == "message"
    assert decision["review_required"] is True
    assert decision["semantic_risk"] == "high"
    assert "structural_mismatch" in decision["context_flags"]
    assert "role_entity_misalignment" in decision["context_flags"]
    assert "sentence_collapse" in decision["context_flags"]
    assert "semantic_similarity_low" in decision["context_flags"]
    assert decision["semantic_similarity"] < 0.35
    assert decision["semantic_evidence"]["shape_preserved"] is False
    assert decision["semantic_evidence"]["action_preserved"] is False
    assert decision["semantic_evidence"]["entity_alignment_ok"] is False
    assert "sentence shape was not preserved" in decision["review_reason"]


def test_key_shape_and_usage_context_infer_notification_body() -> None:
    inferred = infer_text_type(
        "ride_cancelled_notification",
        "Your ride was cancelled by the driver.",
        ["notification_body"],
    )

    assert inferred == "notification_body"


def test_languagetool_signals_support_but_do_not_override_semantic_guard() -> None:
    bundle = build_context_bundle(
        "admin_message",
        "Send approval request to administration.",
        "إرسال طلب الموافقة إلى الإدارة.",
        usage_locations=["helper_text"],
        usage_metadata={
            "ui_surfaces": ["form"],
            "text_roles": ["message"],
            "action_hints": ["action"],
            "audience_hints": ["role_specific"],
            "sentence_shapes": ["sentence_like"],
        },
        linguistic_signals={"lt_grammar_flags": 3, "lt_style_flags": 2, "lt_literalness_support": True, "sources": ["languagetool", "language_tool_python"]},
        role_identifiers=["المدير"],
        entity_whitelist={"en": ["administration"], "ar": ["الإدارة"]},
    )

    decision = evaluate_candidate_change(
        bundle, "المدير", role_identifiers=["المدير"], entity_whitelist={"en": ["administration"], "ar": ["الإدارة"]}
    )

    assert bundle["linguistic_signals"]["lt_grammar_flags"] == 3
    assert bundle["linguistic_signals"]["lt_literalness_support"] is True
    assert decision["review_required"] is True
    assert decision["semantic_risk"] == "high"
    assert decision["semantic_evidence"]["entity_alignment_ok"] is False


def test_context_bundle_marks_missing_action_hints_for_sentence_pair() -> None:
    bundle = build_context_bundle(
        "save_profile_helper",
        "Save your profile to continue.",
        "الملف الشخصي للمتابعة",
        usage_locations=["helper_text"],
        usage_metadata={
            "ui_surfaces": ["form"],
            "text_roles": ["message"],
            "action_hints": ["action"],
            "audience_hints": ["general"],
            "sentence_shapes": ["sentence_like"],
        },
    )

    assert bundle["semantic_risk"] == "medium"
    assert "missing_action:save" in bundle["semantic_flags"]
    assert bundle["review_reason"] == "Possible meaning loss in the Arabic sentence. Human review required."


def test_semantic_similarity_preserves_aligned_action_sentence() -> None:
    similarity = semantic_similarity(
        "Send approval request to administration.",
        "إرسال طلب الموافقة إلى الإدارة.",
    )

    assert similarity >= 0.6


def test_semantic_similarity_detects_sentence_collapse() -> None:
    similarity = semantic_similarity(
        "Add vehicle details to send approval request to admin.",
        "المدير",
    )

    assert similarity < 0.35


def test_semantic_evidence_payload_exists() -> None:
    bundle = build_context_bundle(
        "save_profile_helper",
        "Save your profile to continue.",
        "احفظ ملفك الشخصي للمتابعة.",
        usage_locations=["helper_text"],
        usage_metadata={"text_roles": ["message"], "action_hints": ["action"], "sentence_shapes": ["sentence_like"]},
    )

    decision = evaluate_candidate_change(bundle, "احفظ ملفك الشخصي للمتابعة.")

    assert decision["semantic_risk"] == "low"
    assert decision["review_required"] is False
    assert decision["semantic_evidence"] == {
        "current_semantic_similarity": bundle["current_semantic_similarity"],
        "candidate_semantic_similarity": decision["semantic_similarity"],
        "similarity_drop": 0.0,
        "shape_preserved": True,
        "action_preserved": True,
        "entity_alignment_ok": True,
    }


def test_semantic_drop_without_shape_collapse_triggers_medium() -> None:
    bundle = build_context_bundle(
        "save_profile_helper",
        "Save your profile to continue.",
        "احفظ ملفك الشخصي للمتابعة.",
        usage_locations=["helper_text"],
        usage_metadata={"text_roles": ["message"], "action_hints": ["action"], "sentence_shapes": ["sentence_like"]},
    )

    decision = evaluate_candidate_change(bundle, "تابع من الملف الشخصي.")

    assert decision["semantic_risk"] == "medium"
    assert decision["review_required"] is True
    assert decision["semantic_evidence"]["shape_preserved"] is True
    assert decision["semantic_evidence"]["action_preserved"] is False
    assert "action intent was not preserved" in decision["review_reason"] or "semantic similarity dropped" in decision["review_reason"]


def test_semantic_evidence_is_deterministic() -> None:
    bundle = build_context_bundle(
        "save_profile_helper",
        "Save your profile to continue.",
        "احفظ ملفك الشخصي للمتابعة.",
        usage_locations=["helper_text"],
        usage_metadata={"text_roles": ["message"], "action_hints": ["action"], "sentence_shapes": ["sentence_like"]},
    )

    decision_a = evaluate_candidate_change(bundle, "تابع من الملف الشخصي.")
    decision_b = evaluate_candidate_change(bundle, "تابع من الملف الشخصي.")

    assert decision_a["semantic_evidence"] == decision_b["semantic_evidence"]
