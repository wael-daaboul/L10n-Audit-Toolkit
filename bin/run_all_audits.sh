#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RESULTS_DIR="$TOOLS_DIR/Results"
STAGE="full"

mkdir -p "$RESULTS_DIR"

usage() {
  cat <<'EOF'
Usage: ./tools/bin/run_all_audits.sh [--stage fast|full|grammar|terminology|placeholders|ar-qc|ar-semantic|icu|reports|autofix]

Main workflow outputs:
- Dashboard:    Results/final/final_audit_report.md
- Review queue: Results/review/review_queue.xlsx
- Final locale: Results/final_locale/ar.final.json
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stage)
      STAGE="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

run_python() {
  local module="$1"
  shift
  cd "$TOOLS_DIR"
  python3 -m "$module" "$@"
}

print_profile_selection() {
  cd "$TOOLS_DIR"
  python3 - <<'PY'
from core.audit_runtime import load_runtime
from core.audit_runtime import AuditRuntimeError

try:
    runtime = load_runtime("bin/run_all_audits.sh", validate=False)
except AuditRuntimeError as exc:
    print("Unable to prepare runtime from config/config.json.")
    print(str(exc))
    print()
    print("Recommended next steps:")
    print("- Run 'l10n-audit init' from the project root to generate a local workspace")
    print("- Or copy config/config.example.json and adjust project_root if needed")
    print("- Or set L10N_AUDIT_CONFIG to a project-specific config file")
    raise SystemExit(1)

print(f"Project profile: {runtime.project_profile} ({runtime.profile_selection_mode})")
if runtime.profile_selection_mode == "auto":
    print(f"Detection score: {runtime.profile_score}")
print("Reasons:")
for reason in runtime.profile_reasons:
    print(f"- {reason}")
print()
PY
}

print_profile_selection

run_fast() {
  echo "Running localization audit..."
  "$SCRIPT_DIR/l10n_audit.sh"

  echo "Running advanced localization audit..."
  run_python "audits.l10n_audit_pro"

  echo "Running English locale QC..."
  run_python "audits.en_locale_qc"

  echo "Running Arabic locale QC..."
  run_python "audits.ar_locale_qc"

  echo "Running Arabic semantic review..."
  run_python "audits.ar_semantic_qc"

  echo "Running placeholder validation..."
  run_python "audits.placeholder_audit"

  echo "Running terminology validation..."
  run_python "audits.terminology_audit"
}

case "$STAGE" in
  fast)
    run_fast
    echo "Aggregating reports..."
    run_python "reports.report_aggregator" --sources "localization,locale_qc,ar_locale_qc,ar_semantic_qc,terminology,placeholders"
    ;;
  full)
    run_fast
    echo "Running ICU message audit..."
    run_python "audits.icu_message_audit"
    echo "Running English grammar audit..."
    run_python "audits.en_grammar_audit"
    echo "Aggregating reports..."
    run_python "reports.report_aggregator" --sources "localization,locale_qc,ar_locale_qc,ar_semantic_qc,terminology,placeholders,icu_message_audit,grammar"
    ;;
  grammar)
    echo "Running English grammar audit..."
    run_python "audits.en_grammar_audit"
    ;;
  terminology)
    echo "Running terminology validation..."
    run_python "audits.terminology_audit"
    ;;
  placeholders)
    echo "Running placeholder validation..."
    run_python "audits.placeholder_audit"
    ;;
  ar-qc)
    echo "Running Arabic locale QC..."
    run_python "audits.ar_locale_qc"
    ;;
  ar-semantic)
    echo "Running Arabic semantic review..."
    run_python "audits.ar_semantic_qc"
    ;;
  icu)
    echo "Running ICU message audit..."
    run_python "audits.icu_message_audit"
    ;;
  reports)
    echo "Aggregating reports..."
    run_python "reports.report_aggregator"
    ;;
  autofix)
    echo "Generating safe fix plan..."
    run_python "fixes.apply_safe_fixes"
    ;;
  *)
    echo "Unsupported stage: $STAGE" >&2
    usage >&2
    exit 1
    ;;
esac

echo
echo "Generated reports:"
find "$RESULTS_DIR" -maxdepth 3 -type f | sort | sed "s|$TOOLS_DIR/||"
echo
echo "Primary workflow artifacts:"
echo "- Results/final/final_audit_report.md"
echo "- Results/review/review_queue.xlsx"
echo "- Results/fixes/safe_fixes_applied_report.json (after --stage autofix)"
echo "- Results/final_locale/ar.final.json (after approved review fixes are applied)"
