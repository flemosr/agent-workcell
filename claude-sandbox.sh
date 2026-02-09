#!/bin/bash
# Claude Code Sandbox CLI
#
# Usage:
#   claude-sandbox run [options]           Run the sandbox in current directory
#   claude-sandbox start-chrome [options]  Start Chrome with remote debugging
#   claude-sandbox help                    Show this help message
#
# For detailed help on each command:
#   claude-sandbox run --help
#   claude-sandbox start-chrome --help

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

show_help() {
    cat << 'EOF'
Claude Code Sandbox - Run Claude Code safely in Docker

Usage:
  claude-sandbox <command> [options]

Commands:
  run             Run the sandbox in current directory (default)
  start-chrome    Start Chrome with remote debugging (run on host)
  help            Show this help message

Examples:
  claude-sandbox run
  claude-sandbox run --yolo --with-chrome --port 3000
  claude-sandbox start-chrome
  claude-sandbox start-chrome --restart

For more information, see README.md
EOF
}

show_run_help() {
    cat << 'EOF'
Run the Claude Code sandbox in the current directory

Usage:
  claude-sandbox run [options] [-- claude-args]

Options:
  --yolo            Enable YOLO mode (no permission prompts)
  --firewalled      Restrict network to essential domains only
  --with-chrome     Start Chrome with remote debugging
  --port <port>     Expose a port for dev servers (can be repeated)

Examples:
  claude-sandbox run
  claude-sandbox run --yolo
  claude-sandbox run --yolo --with-chrome --port 3000
  claude-sandbox run --port 3000 --port 5173
  claude-sandbox run --yolo -p "fix the tests"
EOF
}

ensure_docker_running() {
    # Use "docker ps" as a lightweight check — it only needs the daemon to respond,
    # unlike "docker info" which can fail on permission or timeout issues even when
    # Docker is running.
    if docker ps &>/dev/null; then
        return 0
    fi

    echo "Docker is not running. Attempting to start Docker..."

    case "$(uname -s)" in
        Darwin)
            open -a Docker 2>/dev/null || open -a "Docker Desktop" 2>/dev/null || {
                echo "Error: Could not start Docker Desktop. Please start it manually."
                exit 1
            }
            ;;
        Linux)
            if command -v systemctl &>/dev/null; then
                sudo systemctl start docker 2>/dev/null || {
                    echo "Error: Could not start Docker via systemctl. Please start it manually."
                    exit 1
                }
            elif command -v service &>/dev/null; then
                sudo service docker start 2>/dev/null || {
                    echo "Error: Could not start Docker via service. Please start it manually."
                    exit 1
                }
            else
                echo "Error: Could not determine how to start Docker. Please start it manually."
                exit 1
            fi
            ;;
        *)
            echo "Error: Unsupported platform. Please start Docker manually."
            exit 1
            ;;
    esac

    # Wait for Docker to be ready
    echo "Waiting for Docker to be ready..."
    local retries=30
    while ! docker ps &>/dev/null; do
        retries=$((retries - 1))
        if [[ $retries -le 0 ]]; then
            echo "Error: Docker did not start in time. Please start it manually."
            exit 1
        fi
        sleep 2
    done
    echo "Docker is ready."
}

show_start_chrome_help() {
    cat << 'EOF'
Start Chrome with remote debugging for sandbox connection

Usage:
  claude-sandbox start-chrome [options]

Options:
  --port <port>       Override debug port from config
  --profile <name>    Override Chrome profile from config
  --restart, -r       Kill running Chrome and restart with debugging

Examples:
  claude-sandbox start-chrome
  claude-sandbox start-chrome --restart
  claude-sandbox start-chrome --port 9333 --profile "Profile 1"

Note: Chrome must not be running, or use --restart to auto-restart it.
EOF
}

# Parse command
command="${1:-}"

case "$command" in
    run|"")
        # Default command: run sandbox
        shift 2>/dev/null || true

        if [[ "$1" == "--help" || "$1" == "-h" ]]; then
            show_run_help
            exit 0
        fi

        ensure_docker_running
        exec "$SCRIPT_DIR/scripts/run_sandbox.sh" "$@"
        ;;

    start-chrome)
        shift

        if [[ "$1" == "--help" || "$1" == "-h" ]]; then
            show_start_chrome_help
            exit 0
        fi

        exec "$SCRIPT_DIR/scripts/start-chrome-debug.sh" "$@"
        ;;

    help|--help|-h)
        show_help
        exit 0
        ;;

    *)
        # Unknown command - could be flags for open-workspace (backwards compat)
        # Check if it looks like a flag
        if [[ "$command" == -* ]]; then
            ensure_docker_running
            exec "$SCRIPT_DIR/scripts/run_sandbox.sh" "$@"
        else
            echo "Unknown command: $command"
            echo ""
            show_help
            exit 1
        fi
        ;;
esac
