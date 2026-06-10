#!/bin/bash
# Browser control CLI wrapper
# Usage: browser sandbox <command> [args]
#        browser host <command> [args]

VENV_PATH="$HOME/.local/python-venv"
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

source "$VENV_PATH/bin/activate"
python3 "$SCRIPT_DIR/browser.py" "$@"
