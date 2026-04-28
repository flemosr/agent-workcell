#!/bin/bash
# Flutter bridge control CLI wrapper (container-side)
# Usage: flutterctl <command> [args]
#
# Commands:
#   test                    - Test connection to Flutter bridge
#   status                  - Get bridge status (includes ui_automation capabilities)
#   devices                 - List available Flutter devices
#   launch [-d <device>]    - Launch Flutter app
#   attach [-d <device>]    - Attach to running Flutter app
#   detach                  - Detach/stop Flutter app
#   hot-reload              - Hot reload
#   hot-restart             - Hot restart
#   logs                    - Get recent Flutter logs
#   screenshot -o <path>    - Take screenshot (macOS captures app window only)
#   tap                     - UI automation tap (coordinates or text/key selector)
#   type <text>             - Type text into current focus
#   press <key>             - Press a named key or combination (e.g. enter, command+r)
#   scroll                  - Scroll by delta (--dx/--dy) or to edge (--edge)
#   inspect                 - Inspect UI state / semantics tree
#   wait                    - Wait for element matching text/key to appear

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
exec python3 "$SCRIPT_DIR/flutterctl.py" "$@"
