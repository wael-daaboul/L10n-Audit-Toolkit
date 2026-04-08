from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_no_legacy_apply_reference_in_primary_docs():
    files = [
        ROOT / "README.md",
        ROOT / "docs" / "quickstart.md",
        ROOT / "docs" / "review_workflow.md",
        ROOT / "docs" / "output_reports.md",
        ROOT / "docs" / "user_guides" / "USAGE_AR.md",
        ROOT / "docs" / "user_guides" / "HOW_TO_USE.md",
    ]

    forbidden = [
        "الافتراضي: `Results/review/review_queue.xlsx`",
        "default: `Results/review/review_queue.xlsx`",
        "apply uses review_queue.xlsx",
        "apply reads review_queue.xlsx",
        "apply from review_queue.xlsx",
    ]

    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
    for needle in forbidden:
        assert needle not in combined


def test_prepare_apply_is_present_in_primary_docs():
    files = [
        ROOT / "README.md",
        ROOT / "docs" / "quickstart.md",
        ROOT / "docs" / "review_workflow.md",
        ROOT / "docs" / "user_guides" / "USAGE_AR.md",
    ]

    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "prepare-apply" in combined
