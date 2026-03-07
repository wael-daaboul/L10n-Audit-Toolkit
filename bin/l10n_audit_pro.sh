#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$TOOLS_DIR"
cd "$TOOLS_DIR"
python3 -m audits.l10n_audit_pro "$@"
