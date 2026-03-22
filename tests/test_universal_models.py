from l10n_audit.models import AuditOptions, AuditRules

def test_audit_options_universal_defaults():
    opts = AuditOptions()
    assert opts.audit_rules.role_identifiers == []
    assert opts.audit_rules.entity_whitelist == {"en": [], "ar": []}

def test_audit_options_custom_domain():
    opts = AuditOptions(
        audit_rules=AuditRules(
            role_identifiers=["doctor", "patient"],
            entity_whitelist={"en": ["clinic"], "ar": ["عيادة"]}
        )
    )
    assert "doctor" in opts.audit_rules.role_identifiers
    assert "clinic" in opts.audit_rules.entity_whitelist["en"]
    assert "عيادة" in opts.audit_rules.entity_whitelist["ar"]
