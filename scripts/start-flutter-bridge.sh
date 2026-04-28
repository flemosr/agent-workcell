#!/bin/bash
# Start Flutter bridge for Agent Workcell connection
#
# Run this script on your HOST BEFORE starting the Agent Workcell.
# The sandbox will connect to the Flutter bridge via host.docker.internal.
#
# Configuration:
#   Settings are loaded from config.sh. Command line args can override.
#
# Usage:
#   ./start-flutter-bridge.sh                        # Use current directory
#   ./start-flutter-bridge.sh --port 8766            # Override port
#   ./start-flutter-bridge.sh --project /path/to/app # Override project dir

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Find config file
if [ -f "$REPO_ROOT/config.sh" ]; then
    CONFIG_FILE="$REPO_ROOT/config.sh"
else
    echo "Error: No config file found in $REPO_ROOT"
    echo ""
    echo "Please create config.sh from the template:"
    echo ""
    echo "  cd $REPO_ROOT"
    echo "  cp config.template.sh config.sh"
    echo ""
    echo "Then edit config.sh with your Flutter settings."
    echo ""
    exit 1
fi

source "$CONFIG_FILE"

# Apply defaults for optional config
FLUTTER_BRIDGE_PORT="${FLUTTER_BRIDGE_PORT:-${FLUTTER_DEFAULT_BRIDGE_PORT:-8765}}"
flutter_project_dir="$PWD"
flutter_target_override=""
flutter_run_args_override=""
FLUTTER_PATH="${FLUTTER_PATH:-flutter}"

# Check if flutter is available
if ! command -v "$FLUTTER_PATH" &> /dev/null; then
    echo "Error: flutter executable not found: $FLUTTER_PATH"
    echo "Install Flutter from https://docs.flutter.dev/get-started/install or set FLUTTER_PATH in config.sh."
    exit 1
fi

FLUTTER_BRIDGE_LOG_FILE="${FLUTTER_BRIDGE_LOG_FILE:-/tmp/flutter-bridge.log}"

# Parse override arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --port|-p)
            FLUTTER_BRIDGE_PORT="$2"
            shift 2
            ;;
        --project)
            flutter_project_dir="$2"
            shift 2
            ;;
        --target)
            flutter_target_override="$2"
            shift 2
            ;;
        --token)
            FLUTTER_BRIDGE_TOKEN="$2"
            shift 2
            ;;
        --run-args)
            flutter_run_args_override="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--port PORT] [--project DIR] [--target FILE] [--run-args ARGS] [--token TOKEN]"
            exit 1
            ;;
    esac
done

# Validate project directory
if [ ! -d "$flutter_project_dir" ]; then
    echo "Error: Flutter project directory not found: $flutter_project_dir"
    exit 1
fi

flutter_config_file="${flutter_project_dir}/.workcell/flutter-config.json"
flutter_target=$(python3 - "$flutter_config_file" <<'PY'
import json
import sys

path = sys.argv[1]
target = "lib/main.dart"
try:
    with open(path) as f:
        config = json.load(f)
    if isinstance(config, dict) and isinstance(config.get("target"), str) and config["target"]:
        target = config["target"]
except (FileNotFoundError, json.JSONDecodeError, OSError):
    pass
print(target)
PY
)
flutter_run_args=$(python3 - "$flutter_config_file" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    with open(path) as f:
        config = json.load(f)
    run_args = config.get("run_args", []) if isinstance(config, dict) else []
except (FileNotFoundError, json.JSONDecodeError, OSError):
    run_args = []
if isinstance(run_args, list) and run_args:
    print(json.dumps([str(item) for item in run_args], separators=(",", ":")))
elif isinstance(run_args, str) and run_args:
    print(run_args)
PY
)
if [ -n "$flutter_target_override" ]; then
    flutter_target="$flutter_target_override"
fi
if [ -n "$flutter_run_args_override" ]; then
    flutter_run_args="$flutter_run_args_override"
fi

# Check if port is in use
if lsof -i :$FLUTTER_BRIDGE_PORT >/dev/null 2>&1; then
    echo "Error: Port $FLUTTER_BRIDGE_PORT is already in use."
    exit 1
fi

# Truncate log file for fresh start
: > "$FLUTTER_BRIDGE_LOG_FILE"

# Set up logging. Keep user-facing launcher messages on stderr and bridge
# stdout in the configured log file.
exec 3>&1  # Save original stdout
exec > "$FLUTTER_BRIDGE_LOG_FILE" 2>&1
# Restore stderr to terminal for user-facing messages
exec 2>&3 3>&-

echo "Starting Flutter Bridge..." >&2
echo "  Port: $FLUTTER_BRIDGE_PORT" >&2
echo "  Project: $flutter_project_dir" >&2
echo "  Target: $flutter_target" >&2
if [ -n "$flutter_run_args" ]; then
    echo "  Run args: $flutter_run_args" >&2
fi
echo "  Log: $FLUTTER_BRIDGE_LOG_FILE" >&2
echo "" >&2

# Generate token if not set
if [ -z "$FLUTTER_BRIDGE_TOKEN" ]; then
    FLUTTER_BRIDGE_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(16))" 2>/dev/null || \
                           openssl rand -hex 16 2>/dev/null || \
                           od -vAn -N16 -tx1 /dev/urandom | tr -d ' \n')
    echo "  Generated token: $FLUTTER_BRIDGE_TOKEN" >&2
    echo "  Token written to: ${flutter_project_dir}/.workcell/flutter-config.json" >&2
else
    echo "  Using provided bridge token." >&2
fi

# Write bridge config to project .workcell/ so agents inside a container
# mounted with this project directory can discover the bridge automatically.
mkdir -p "${flutter_project_dir}/.workcell"
python3 - "$flutter_config_file" "$FLUTTER_BRIDGE_TOKEN" "$FLUTTER_BRIDGE_PORT" "$flutter_target_override" "$flutter_run_args_override" <<'PY'
import json
import sys

path, token, port, target_override, run_args_override = (
    sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
)
try:
    with open(path) as f:
        config = json.load(f)
    if not isinstance(config, dict):
        config = {}
except (FileNotFoundError, json.JSONDecodeError, OSError):
    config = {}
config["token"] = token
config["port"] = port
if target_override:
    config["target"] = target_override
if run_args_override:
    try:
        parsed_run_args = json.loads(run_args_override)
    except json.JSONDecodeError:
        config["run_args"] = run_args_override
    else:
        config["run_args"] = (
            parsed_run_args if isinstance(parsed_run_args, list) else run_args_override
        )
with open(path, "w") as f:
    json.dump(config, f, indent=4)
    f.write("\n")
PY

exec python3 "$SCRIPT_DIR/flutter-bridge.py" \
    --port "$FLUTTER_BRIDGE_PORT" \
    --host "0.0.0.0" \
    --project-dir "$flutter_project_dir" \
    --target "$flutter_target" \
    --flutter-path "$FLUTTER_PATH" \
    --token "$FLUTTER_BRIDGE_TOKEN" \
    --log-file "$FLUTTER_BRIDGE_LOG_FILE" \
    ${flutter_run_args:+--run-args "$flutter_run_args"}
