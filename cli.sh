#!/bin/bash
# Agent Sandbox CLI
#
# Usage:
#   agent-sandbox run [agent] [options]   Run the sandbox in current directory
#                                          (agent: claude [default] | opencode)
#   agent-sandbox start-chrome [options]  Start Chrome with remote debugging
#   agent-sandbox gpg-new                  Generate a new sandbox GPG key
#   agent-sandbox gpg-export --file <f>    Export sandbox GPG key to a file
#   agent-sandbox gpg-import --file <f>   Import a GPG key into the sandbox
#   agent-sandbox gpg-revoke --file <f>   Generate a revocation certificate
#   agent-sandbox gpg-erase               Erase the sandbox GPG key
#   agent-sandbox volume-shell             Open a shell in the sandbox volume
#   agent-sandbox volume-backup --file <f> Backup the sandbox volume
#   agent-sandbox volume-restore --file <f> Restore the sandbox volume from backup
#   agent-sandbox volume-rm               Remove the sandbox volume
#   agent-sandbox settings <agent>        Open an agent's settings/config in vi
#   agent-sandbox help                    Show this help message
#
# For detailed help on each command:
#   agent-sandbox run --help
#   agent-sandbox start-chrome --help

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ensure common Docker CLI locations are on PATH.
# IDE task runners (e.g. Zed, VS Code) may launch with a minimal environment
# that doesn't include the directories where Docker Desktop installs its CLI.
for p in /usr/local/bin /opt/homebrew/bin "$HOME/.docker/bin"; do
    if [[ -d "$p" ]] && [[ ":$PATH:" != *":$p:"* ]]; then
        export PATH="$p:$PATH"
    fi
done

show_help() {
    cat << 'EOF'
Agent Sandbox - Run coding agents safely in Docker

Usage:
  agent-sandbox <command> [options]

Commands:
  run [agent]     Run the sandbox in current directory (default: claude)
                  agent: claude | opencode
  start-chrome    Start Chrome with remote debugging (run on host)
  gpg-new         Generate a new sandbox GPG key
  gpg-export      Export the sandbox GPG key to a file
  gpg-import      Import a GPG key into the sandbox
  gpg-revoke      Generate a revocation certificate
  gpg-erase       Erase the sandbox GPG key
  volume-shell    Open a shell in the sandbox volume
  volume-backup   Backup the sandbox volume to a file
  volume-restore  Restore the sandbox volume from a backup
  volume-rm       Remove the sandbox volume
  settings <agent>   Open an agent's settings/config in vi
  help            Show this help message

Examples:
  agent-sandbox run
  agent-sandbox run claude --yolo --with-chrome --port 3000
  agent-sandbox run opencode --yolo
  agent-sandbox start-chrome
  agent-sandbox start-chrome --restart
  agent-sandbox gpg-new
  agent-sandbox gpg-export --file my-key.asc
  agent-sandbox gpg-import --file my-key.asc
  agent-sandbox gpg-revoke --file revoke.asc
  agent-sandbox gpg-erase
  agent-sandbox volume-shell
  agent-sandbox volume-backup --file backup.tgz
  agent-sandbox volume-restore --file backup.tgz
  agent-sandbox volume-rm
  agent-sandbox settings claude
  agent-sandbox settings opencode

For more information, see README.md
EOF
}

show_run_help() {
    cat << 'EOF'
Run the Agent Sandbox in the current directory

Usage:
  agent-sandbox run [agent] [options] [-- agent-args]

Agents:
  claude     (default) Launch Claude Code
  opencode   Launch opencode

Options:
  --yolo            Enable YOLO mode (no permission prompts)
                    claude:   passes --dangerously-skip-permissions
                    opencode: injects {"permission":"allow"} via
                              OPENCODE_CONFIG_CONTENT
  --firewalled      Restrict network to essential domains only
  --with-chrome     Start Chrome with remote debugging
  --port <port>     Expose a port for dev servers (can be repeated)

Examples:
  agent-sandbox run
  agent-sandbox run claude --yolo
  agent-sandbox run opencode --yolo
  agent-sandbox run claude --yolo --with-chrome --port 3000
  agent-sandbox run opencode --port 3000 --port 5173
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
  agent-sandbox start-chrome [options]

Options:
  --port <port>       Override debug port from config
  --profile <name>    Override Chrome profile from config
  --restart, -r       Kill running Chrome and restart with debugging

Examples:
  agent-sandbox start-chrome
  agent-sandbox start-chrome --restart
  agent-sandbox start-chrome --port 9333 --profile "Profile 1"

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

    gpg-new)
        shift
        if [[ "$1" == "--help" || "$1" == "-h" ]]; then
            echo "Generate a new sandbox GPG key"
            echo ""
            echo "Usage:"
            echo "  agent-sandbox gpg-new"
            echo ""
            echo "Reads GIT_AUTHOR_NAME and GIT_AUTHOR_EMAIL from config.sh."
            echo "If a key already exists, prompts before overwriting."
            exit 0
        fi

        # Source config for identity
        if [ -f "$SCRIPT_DIR/config.sh" ]; then
            source "$SCRIPT_DIR/config.sh"
        fi

        if [ -z "$GIT_AUTHOR_NAME" ] || [ -z "$GIT_AUTHOR_EMAIL" ]; then
            echo "Error: GIT_AUTHOR_NAME and GIT_AUTHOR_EMAIL must be set in config.sh"
            exit 1
        fi

        ensure_docker_running

        # Check for existing key
        existing=$(docker run --rm --entrypoint bash -v agent-sandbox:/data local/agent-sandbox \
            -c 'gpg --homedir /data/.gnupg --no-permission-warning --list-keys --with-colons 2>/dev/null | grep "^uid" | head -1 | cut -d: -f10')

        if [ -n "$existing" ]; then
            echo "An existing GPG key was found: $existing"
            echo "Generating a new key will erase the existing one."
            echo ""
            read -r -p "Continue? [y/N] " confirm
            case "$confirm" in
                y|Y) ;;
                *)
                    echo "Aborted."
                    exit 0
                    ;;
            esac
            docker run --rm --entrypoint bash -v agent-sandbox:/data local/agent-sandbox \
                -c 'rm -rf /data/.gnupg/*'
        fi

        echo "Generating GPG signing key for $GIT_AUTHOR_NAME <$GIT_AUTHOR_EMAIL>..."
        docker run --rm --entrypoint bash -v agent-sandbox:/data \
            -e "GIT_AUTHOR_NAME=$GIT_AUTHOR_NAME" \
            -e "GIT_AUTHOR_EMAIL=$GIT_AUTHOR_EMAIL" \
            local/agent-sandbox \
            -c '
                gpg --homedir /data/.gnupg --no-permission-warning --batch --gen-key <<GPGEOF
%no-protection
Key-Type: eddsa
Key-Curve: ed25519
Name-Real: $GIT_AUTHOR_NAME
Name-Email: $GIT_AUTHOR_EMAIL
Expire-Date: 0
%commit
GPGEOF
                echo ""
                echo "=== GPG Public Key (add to GitHub → Settings → SSH and GPG keys) ==="
                gpg --homedir /data/.gnupg --no-permission-warning --armor --export "$GIT_AUTHOR_EMAIL"
                echo "==================================================================="
                chown -R 1000:1000 /data/.gnupg
            '
        ;;

    gpg-export)
        shift
        outfile=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --file) outfile="$2"; shift 2 ;;
                --help|-h)
                    echo "Export the sandbox GPG key to a file"
                    echo ""
                    echo "Usage:"
                    echo "  agent-sandbox gpg-export --file <path>"
                    echo ""
                    echo "Options:"
                    echo "  --file <path>   Output file (required)"
                    exit 0
                    ;;
                *) echo "Unknown option: $1"; exit 1 ;;
            esac
        done

        if [ -z "$outfile" ]; then
            echo "Error: --file is required"
            echo "Usage: agent-sandbox gpg-export --file <path>"
            exit 1
        fi

        ensure_docker_running
        docker run --rm --entrypoint bash -v agent-sandbox:/data local/agent-sandbox \
            -c 'gpg --homedir /data/.gnupg --no-permission-warning --export-secret-keys --armor 2>/dev/null' > "$outfile"

        if [ ! -s "$outfile" ]; then
            rm -f "$outfile"
            echo "Error: No GPG keys found in the sandbox volume."
            exit 1
        fi

        echo "Exported GPG key to: $outfile"
        echo "WARNING: This file contains your PRIVATE key. Do not commit or share it."
        ;;

    gpg-import)
        shift
        infile=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --file) infile="$2"; shift 2 ;;
                --help|-h)
                    echo "Import a GPG key into the sandbox"
                    echo ""
                    echo "Usage:"
                    echo "  agent-sandbox gpg-import --file <key-file>"
                    echo ""
                    echo "Options:"
                    echo "  --file <path>   Key file to import (required)"
                    exit 0
                    ;;
                *) echo "Unknown option: $1"; exit 1 ;;
            esac
        done

        if [ -z "$infile" ]; then
            echo "Error: --file is required"
            echo "Usage: agent-sandbox gpg-import --file <key-file>"
            exit 1
        fi

        if [ ! -f "$infile" ]; then
            echo "Error: File not found: $infile"
            exit 1
        fi

        ensure_docker_running
        docker run --rm -i --entrypoint bash -v agent-sandbox:/data local/agent-sandbox \
            -c '
                gpg --homedir /data/.gnupg --no-permission-warning --import && \
                fpr=$(gpg --homedir /data/.gnupg --no-permission-warning --list-keys --with-colons 2>/dev/null | grep "^fpr" | head -1 | cut -d: -f10) && \
                if [ -n "$fpr" ]; then
                    echo "$fpr:6:" | gpg --homedir /data/.gnupg --no-permission-warning --import-ownertrust
                fi && \
                chown -R 1000:1000 /data/.gnupg
            ' < "$infile"
        echo "GPG key imported into the sandbox."
        ;;

    gpg-revoke)
        shift
        outfile=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --file) outfile="$2"; shift 2 ;;
                --help|-h)
                    echo "Generate a revocation certificate for the sandbox GPG key"
                    echo ""
                    echo "Usage:"
                    echo "  agent-sandbox gpg-revoke --file <path>"
                    echo ""
                    echo "Options:"
                    echo "  --file <path>   Output file (required)"
                    echo ""
                    echo "Upload the certificate to GitHub to invalidate the key."
                    echo "Commits signed before revocation remain verified."
                    exit 0
                    ;;
                *) echo "Unknown option: $1"; exit 1 ;;
            esac
        done

        if [ -z "$outfile" ]; then
            echo "Error: --file is required"
            echo "Usage: agent-sandbox gpg-revoke --file <path>"
            exit 1
        fi

        ensure_docker_running

        # Resolve to absolute path and mount the parent directory
        outdir="$(cd "$(dirname "$outfile")" && pwd)"
        outname="$(basename "$outfile")"

        docker run --rm -it --entrypoint bash \
            -v agent-sandbox:/data \
            -v "$outdir:/output" \
            -e "OUTNAME=$outname" \
            local/agent-sandbox \
            -c '
                key_id=$(gpg --homedir /data/.gnupg --no-permission-warning --list-keys --keyid-format long 2>/dev/null | grep -oP "(?<=ed25519/)[A-F0-9]+" | head -1)
                if [ -z "$key_id" ]; then
                    echo "Error: No GPG keys found in the sandbox volume." >&2
                    exit 1
                fi
                gpg --homedir /data/.gnupg --no-permission-warning --gen-revoke --output "/output/$OUTNAME" "$key_id"
            '

        if [ ! -s "$outfile" ]; then
            rm -f "$outfile"
            echo "Error: Failed to generate revocation certificate."
            exit 1
        fi

        echo "Revocation certificate written to: $outfile"
        echo "Upload this to GitHub to invalidate the key."
        ;;

    gpg-erase)
        shift
        if [[ "$1" == "--help" || "$1" == "-h" ]]; then
            echo "Erase the sandbox GPG key"
            echo ""
            echo "Usage:"
            echo "  agent-sandbox gpg-erase"
            echo ""
            echo "This permanently deletes all GPG keys from the sandbox volume."
            echo "A new key will be generated on the next launch if GPG_SIGNING is enabled."
            exit 0
        fi

        read -r -p "This will permanently delete all GPG keys from the sandbox. Continue? [y/N] " confirm
        case "$confirm" in
            y|Y)
                ensure_docker_running
                docker run --rm --entrypoint bash -v agent-sandbox:/data local/agent-sandbox \
                    -c 'rm -rf /data/.gnupg/* && echo "GPG keys erased."'
                ;;
            *)
                echo "Aborted."
                ;;
        esac
        ;;

    volume-shell)
        shift
        if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
            echo "Open a shell in the sandbox volume"
            echo ""
            echo "Usage:"
            echo "  agent-sandbox volume-shell"
            echo ""
            echo "Opens an interactive shell in the sandbox Docker volume"
            echo "for inspecting or modifying its contents."
            exit 0
        fi

        ensure_docker_running
        docker run --rm -it -v agent-sandbox:/data -w /data alpine sh
        ;;

    volume-backup)
        shift
        outfile=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --file) outfile="$2"; shift 2 ;;
                --help|-h)
                    echo "Backup the sandbox volume to a file"
                    echo ""
                    echo "Usage:"
                    echo "  agent-sandbox volume-backup --file <path>"
                    echo ""
                    echo "Options:"
                    echo "  --file <path>   Output file (required, .tgz)"
                    exit 0
                    ;;
                *) echo "Unknown option: $1"; exit 1 ;;
            esac
        done

        if [ -z "$outfile" ]; then
            echo "Error: --file is required"
            echo "Usage: agent-sandbox volume-backup --file <path>"
            exit 1
        fi

        ensure_docker_running

        outdir="$(cd "$(dirname "$outfile")" && pwd)"
        outname="$(basename "$outfile")"

        docker run --rm -v agent-sandbox:/data -v "$outdir:/backup" alpine \
            tar -czf "/backup/$outname" -C /data .

        echo "Volume backed up to: $outfile"
        ;;

    volume-restore)
        shift
        infile=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --file) infile="$2"; shift 2 ;;
                --help|-h)
                    echo "Restore the sandbox volume from a backup"
                    echo ""
                    echo "Usage:"
                    echo "  agent-sandbox volume-restore --file <path>"
                    echo ""
                    echo "Options:"
                    echo "  --file <path>   Backup file to restore (required, .tgz)"
                    echo ""
                    echo "WARNING: This replaces all current volume contents."
                    exit 0
                    ;;
                *) echo "Unknown option: $1"; exit 1 ;;
            esac
        done

        if [ -z "$infile" ]; then
            echo "Error: --file is required"
            echo "Usage: agent-sandbox volume-restore --file <path>"
            exit 1
        fi

        if [ ! -f "$infile" ]; then
            echo "Error: File not found: $infile"
            exit 1
        fi

        read -r -p "This will replace all contents of the sandbox volume. Continue? [y/N] " confirm
        case "$confirm" in
            y|Y) ;;
            *)
                echo "Aborted."
                exit 0
                ;;
        esac

        ensure_docker_running

        indir="$(cd "$(dirname "$infile")" && pwd)"
        inname="$(basename "$infile")"

        docker run --rm -v agent-sandbox:/data -v "$indir:/backup" alpine \
            sh -c "rm -rf /data/* /data/.[!.]* /data/..?* 2>/dev/null; tar -xzf /backup/$inname -C /data"

        echo "Volume restored from: $infile"
        ;;

    volume-rm)
        shift
        if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
            echo "Remove the sandbox volume"
            echo ""
            echo "Usage:"
            echo "  agent-sandbox volume-rm"
            echo ""
            echo "Permanently deletes the sandbox Docker volume and all its data"
            echo "(credentials, settings, GPG keys, installed tools, etc.)."
            echo "A fresh volume will be created on the next launch."
            exit 0
        fi

        read -r -p "This will permanently delete all sandbox data (credentials, settings, GPG keys, etc.). Continue? [y/N] " confirm
        case "$confirm" in
            y|Y)
                ensure_docker_running
                docker volume rm agent-sandbox
                echo "Volume 'agent-sandbox' removed."
                ;;
            *)
                echo "Aborted."
                ;;
        esac
        ;;

    settings)
        shift
        if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
            echo "Open an agent's config file in vi (inside the sandbox volume)"
            echo ""
            echo "Usage:"
            echo "  agent-sandbox settings <agent>"
            echo ""
            echo "Agents (required):"
            echo "  claude    ~/.claude/settings.json"
            echo "  opencode  ~/.config/opencode/opencode.jsonc (preferred if it exists)"
            echo "            ~/.config/opencode/opencode.json"
            exit 0
        fi

        if [ -z "${1:-}" ]; then
            echo "Error: agent is required (expected 'claude' or 'opencode')"
            echo "Usage: agent-sandbox settings <agent>"
            exit 1
        fi

        settings_agent="$1"
        ensure_docker_running
        case "$settings_agent" in
            claude)
                docker run --rm -it --entrypoint sh -v agent-sandbox:/data local/agent-sandbox -lc '
                    mkdir -p /data/.claude
                    chown -R claude:claude /data/.claude
                    [ -f /data/.claude/settings.json ] || printf "{}\n" > /data/.claude/settings.json
                    chown claude:claude /data/.claude/settings.json
                    exec runuser -u claude -- vi /data/.claude/settings.json
                '
                ;;
            opencode)
                docker run --rm -it --entrypoint sh -v agent-sandbox:/data local/agent-sandbox -lc '
                    mkdir -p /data/.config/opencode
                    chown -R claude:claude /data/.config/opencode
                    if [ -f /data/.config/opencode/opencode.jsonc ]; then
                        settings_path=/data/.config/opencode/opencode.jsonc
                    else
                        settings_path=/data/.config/opencode/opencode.json
                        if [ ! -f "$settings_path" ]; then
                            cat > "$settings_path" <<EOF
{
  "\$schema": "https://opencode.ai/config.json"
}
EOF
                        fi
                    fi
                    chown claude:claude "$settings_path"
                    exec runuser -u claude -- vi "$settings_path"
                '
                ;;
            *)
                echo "Error: unknown agent '$settings_agent' (expected 'claude' or 'opencode')"
                exit 1
                ;;
        esac
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
