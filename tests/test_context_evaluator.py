from core.context_evaluator import build_context_bundle, evaluate_candidate_change, infer_text_type


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
    )

    decision = evaluate_candidate_change(bundle, "المدير")

    assert bundle["inferred_text_type"] == "helper_text"
    assert bundle["ui_surface"] == "form"
    assert bundle["text_role"] == "message"
    assert decision["review_required"] is True
    assert decision["semantic_risk"] == "high"
    assert "structural_mismatch" in decision["context_flags"]
    assert "role_entity_misalignment" in decision["context_flags"]
    assert "sentence_collapse" in decision["context_flags"]


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
    )

    decision = evaluate_candidate_change(bundle, "المدير")

    assert bundle["linguistic_signals"]["lt_grammar_flags"] == 3
    assert bundle["linguistic_signals"]["lt_literalness_support"] is True
    assert decision["review_required"] is True
    assert decision["semantic_risk"] == "high"


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
