#!/bin/bash
# Flutter bridge control CLI wrapper (container-side)
# Usage: flutterctl <command> [args]
#
# Commands:
#   test                    - Test connection to Flutter bridge
#   status                  - Get bridge status
#   devices                 - List available Flutter devices
#   launch [-d <device>]    - Launch Flutter app
#   attach [-d <device>]    - Attach to running Flutter app
#   detach                  - Detach/stop Flutter app
#   hot-reload              - Hot reload
#   hot-restart             - Hot restart
#   logs                    - Get recent Flutter logs
#   screenshot -o <path>    - Take screenshot

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
exec python3 "$SCRIPT_DIR/flutterctl.py" "$@"
