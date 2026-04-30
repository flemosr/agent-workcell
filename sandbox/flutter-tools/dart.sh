#!/bin/bash
# Container-side Dart wrapper that repairs host-generated package metadata.

set -e

REAL_DART="${WORKCELL_REAL_DART:-/home/agent/persist/.flutter-sdk/bin/dart}"
REAL_FLUTTER="${WORKCELL_REAL_FLUTTER:-/home/agent/persist/.flutter-sdk/bin/flutter}"
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

if [ -x "$REAL_FLUTTER" ]; then
  WORKCELL_REAL_FLUTTER="$REAL_FLUTTER" python3 "$SCRIPT_DIR/package_config_guard.py" "$@"
fi

exec "$REAL_DART" "$@"
