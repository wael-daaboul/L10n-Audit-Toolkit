from l10n_audit.core.context_evaluator import build_context_bundle, evaluate_candidate_change


def test_aligned_sentence_stays_low_risk() -> None:
    bundle = build_context_bundle(
        "send_request_helper",
        "Send approval request to administration.",
        "إرسال طلب الموافقة إلى الإدارة.",
        usage_locations=["helper_text"],
        usage_metadata={"text_roles": ["message"], "action_hints": ["action"], "sentence_shapes": ["sentence_like"]},
        entity_whitelist={"en": ["administration"], "ar": ["الإدارة"]},
    )

    decision = evaluate_candidate_change(
        bundle,
        "إرسال طلب الموافقة إلى الإدارة.",
        entity_whitelist={"en": ["administration"], "ar": ["الإدارة"]},
    )

    assert decision["semantic_risk"] == "low"
    assert decision["review_required"] is False
    assert decision["semantic_evidence"]["candidate_semantic_similarity"] >= 0.6


def test_role_entity_mismatch_stays_explicit_in_evidence() -> None:
    bundle = build_context_bundle(
        "admin_message",
        "Send approval request to administration.",
        "إرسال طلب الموافقة إلى الإدارة.",
        usage_locations=["helper_text"],
        usage_metadata={"text_roles": ["message"], "action_hints": ["action"], "sentence_shapes": ["sentence_like"]},
        role_identifiers=["المدير"],
        entity_whitelist={"en": ["administration"], "ar": ["الإدارة"]},
    )

    decision = evaluate_candidate_change(
        bundle,
        "المدير",
        role_identifiers=["المدير"],
        entity_whitelist={"en": ["administration"], "ar": ["الإدارة"]},
    )

    assert decision["semantic_risk"] == "high"
    assert "role_entity_misalignment" in decision["context_flags"]
    assert decision["semantic_evidence"]["entity_alignment_ok"] is False
