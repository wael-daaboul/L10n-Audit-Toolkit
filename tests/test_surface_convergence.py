from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_apply_surface_no_legacy_direct_queue_reference():
    files = [
        ROOT / "README.md",
        ROOT / "docs" / "review_workflow.md",
        ROOT / "docs" / "quickstart.md",
        ROOT / "docs" / "output_reports.md",
        ROOT / "docs" / "user_guides" / "USAGE_AR.md",
        ROOT / "docs" / "user_guides" / "HOW_TO_USE.md",
        ROOT / "l10n_audit" / "core" / "cli.py",
    ]

    forbidden = [
        "apply uses review_queue.xlsx",
        "apply reads review_queue.xlsx",
        "apply from review_queue.xlsx",
    ]

    for path in files:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for needle in forbidden:
            assert needle not in lowered, f"legacy apply surface reference found in {path}: {needle}"


def test_surface_documents_connected_adaptive_workflow():
    files = [
        ROOT / "README.md",
        ROOT / "docs" / "quickstart.md",
        ROOT / "docs" / "overview.md",
        ROOT / "docs" / "user_guides" / "USAGE_AR.md",
        ROOT / "l10n_audit" / "core" / "cli.py",
    ]

    required_tokens = [
        "generate-adaptation-report",
        "generate-manifest",
        "review-manifest",
        "apply-manifest",
    ]

    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
    for token in required_tokens:
        assert token in combined
