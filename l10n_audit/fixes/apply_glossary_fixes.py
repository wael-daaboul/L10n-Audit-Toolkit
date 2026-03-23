import json
import argparse
from pathlib import Path
from l10n_audit.core.audit_runtime import load_runtime, load_locale_mapping
from l10n_audit.core.glossary_engine import load_glossary_rules, apply_text_replacements
from l10n_audit.core.locale_exporters import export_locale_mapping

def apply_glossary_to_data(data: dict[str, object], rules: dict[str, str]) -> tuple[dict[str, object], int]:
    """Apply replacements to values and return updated data and count."""
    updated = {}
    count = 0
    for key, value in data.items():
        if isinstance(value, str):
            new_value = apply_text_replacements(value, rules)
            if new_value != value:
                updated[key] = new_value
                count += 1
            else:
                updated[key] = value
        else:
            updated[key] = value
    return updated, count

def main() -> None:
    runtime = load_runtime(__file__)
    parser = argparse.ArgumentParser()
    parser.add_argument("--glossary", default=str(runtime.config_dir / "glossary.json"))
    parser.add_argument("--target-file", default=str(runtime.ar_file))
    parser.add_argument("--out", help="Output file path (defaults to overwriting target-file)")
    args = parser.parse_args()

    glossary_path = Path(args.glossary)
    target_path = Path(args.target_file)
    out_path = Path(args.out) if args.out else target_path

    if not target_path.exists():
        print(f"Error: Target file not found: {target_path}")
        return

    rules = load_glossary_rules(glossary_path)
    if not rules:
        print("No glossary rules found or glossary file missing. Nothing to do.")
        return

    # Load target data
    # We use ar_data as target usually
    data = load_locale_mapping(target_path, runtime, "ar")
    
    updated_data, count = apply_glossary_to_data(data, rules)
    
    if count > 0:
        # Save preserving format
        # If it's JSON, we indent 2.
        # If it's Laravel, we'd need export_locale_mapping, but for Phase 4 
        # let's focus on the JSON standard as requested.
        export_locale_mapping(updated_data, "json", out_path)
        print(f"Applied {count} glossary fixes to {out_path}")
    else:
        print("No glossary violations found. File is clean.")

if __name__ == "__main__":
    main()
