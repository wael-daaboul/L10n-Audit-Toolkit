#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_DIR="$SCRIPT_DIR"
VENV_DIR="$TOOLS_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
INSTALL_OPTIONAL=1
INSTALL_DEV=0
RUN_SCHEMA=0
RUN_TESTS=0

usage() {
  cat <<'EOF'
Usage: ./tools/bootstrap.sh [--with-tests] [--skip-optional] [--validate-schemas] [--run-tests]

Options:
  --with-tests         Install development dependencies from requirements-dev.txt
  --skip-optional      Skip optional dependencies from requirements-optional.txt
  --validate-schemas   Run core schema validation after installation
  --run-tests          Run pytest after installation (implies --with-tests)
  --help               Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-tests)
      INSTALL_DEV=1
      shift
      ;;
    --skip-optional)
      INSTALL_OPTIONAL=0
      shift
      ;;
    --validate-schemas)
      RUN_SCHEMA=1
      shift
      ;;
    --run-tests)
      INSTALL_DEV=1
      RUN_TESTS=1
      shift
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

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "python3 is required but was not found on PATH." >&2
  exit 1
fi

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creating virtual environment at $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

VENV_PYTHON="$VENV_DIR/bin/python"
PIP_CMD=("$VENV_PYTHON" -m pip)

echo "Upgrading pip..."
"${PIP_CMD[@]}" install --upgrade pip

echo "Installing required dependencies..."
"${PIP_CMD[@]}" install -r "$TOOLS_DIR/requirements.txt"

if [[ "$INSTALL_OPTIONAL" -eq 1 ]]; then
  echo "Installing optional dependencies..."
  "${PIP_CMD[@]}" install -r "$TOOLS_DIR/requirements-optional.txt"
fi

if [[ "$INSTALL_DEV" -eq 1 ]]; then
  echo "Installing development dependencies..."
  "${PIP_CMD[@]}" install -r "$TOOLS_DIR/requirements-dev.txt"
fi

if [[ "$RUN_SCHEMA" -eq 1 ]]; then
  echo "Running schema validation..."
  (cd "$TOOLS_DIR" && "$VENV_PYTHON" -m core.schema_validation --preset core)
fi

if [[ "$RUN_TESTS" -eq 1 ]]; then
  echo "Running pytest..."
  (cd "$TOOLS_DIR" && "$VENV_PYTHON" -m pytest tests)
fi

cat <<EOF

Bootstrap complete.

Using virtual environment:
  $VENV_DIR

Recommended next steps:
  source "$VENV_DIR/bin/activate"
  ./tools/bin/run_all_audits.sh --stage fast
  ./tools/bin/run_all_audits.sh --stage full

Optional validation commands:
  $VENV_PYTHON -m core.schema_validation --preset core
  $VENV_PYTHON -m pytest tests
EOF
