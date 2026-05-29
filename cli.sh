#!/bin/bash
# Agent Workcell CLI
#
# Usage:
#   workcell build [target] [options] Build/rebuild sandbox images
#   workcell run <agent> [options]   Run the sandbox in current directory
#                                          (agent: claude | opencode | codex | pi)
#   workcell start-chrome [options]  Start Chrome with remote debugging
#   workcell start-flutter-bridge     Start Flutter host bridge
#   workcell gpg-new                  Generate a new sandbox GPG key
#   workcell gpg-export --file <f>    Export sandbox GPG key to a file
#   workcell gpg-import --file <f>   Import a GPG key into the sandbox
#   workcell gpg-revoke --file <f>   Generate a revocation certificate
#   workcell gpg-erase               Erase the sandbox GPG key
#   workcell volume-shell <scope>     Open a shell in a workcell volume
#   workcell volume-backup --file <f> Backup all workcell volumes
#   workcell volume-restore --file <f> Restore all workcell volumes from backup
#   workcell volume-rm <scope>        Remove a workcell volume scope
#   workcell settings <agent>        Open an agent's settings/config in vi
#   workcell opencode-sessions-export Export opencode sessions for current workspace
#   workcell opencode-sessions-import Import opencode sessions from workspace backup
#   workcell help                    Show this help message
#
# For detailed help on each command:
#   workcell run --help
#   workcell start-chrome --help

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKCELL_IMAGE_PREFIX="local/agent-workcell"
WORKCELL_BASE_IMAGE_NAME="local/agent-workcell-base"
WORKCELL_SHARED_GPG_VOLUME_NAME="agent-workcell-gpg"
agent_volume_name() { echo "agent-workcell-$1"; }
agent_image_name() { echo "${WORKCELL_IMAGE_PREFIX}-$1"; }
valid_agent() { case "$1" in claude|opencode|codex|pi) return 0 ;; *) return 1 ;; esac; }

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
Agent Workcell - Run coding agents safely in Docker

Usage:
  workcell <command> [options]

Commands:
  build           Build/rebuild the sandbox image
  run <agent>     Run the sandbox in current directory
                  agent: claude | opencode | codex | pi
  start-chrome    Start Chrome with remote debugging (run on host)
  start-flutter-bridge  Start Flutter host bridge (run on host)
  gpg-new         Generate a new sandbox GPG key
  gpg-export      Export the sandbox GPG key to a file
  gpg-import      Import a GPG key into the sandbox
  gpg-revoke      Generate a revocation certificate
  gpg-erase       Erase the sandbox GPG key
  volume-shell    Open a shell in a workcell volume scope
  volume-backup   Backup all workcell volumes to a file
  volume-restore  Restore all workcell volumes from a backup
  volume-rm       Remove a workcell volume scope
  settings <agent>   Open an agent's settings/config in vi
  opencode-sessions-export  Export opencode sessions for current workspace
                            to .workcell/opencode-sessions/
  opencode-sessions-import  Import opencode sessions from
                            .workcell/opencode-sessions/
  help            Show this help message

Examples:
  workcell build
  workcell run claude --yolo --with-chrome --port 3000
  workcell run opencode --yolo
  workcell run codex --yolo
  workcell run pi
  workcell start-chrome
  workcell start-chrome --restart
  workcell start-flutter-bridge
  workcell gpg-new
  workcell gpg-export --file my-key.asc
  workcell gpg-import --file my-key.asc
  workcell gpg-revoke --file revoke.asc
  workcell gpg-erase
  workcell volume-shell codex
  workcell volume-backup --file backup.tgz
  workcell volume-restore --file backup.tgz
  workcell volume-rm codex
  workcell settings claude
  workcell settings opencode
  workcell settings codex
  workcell settings pi
  workcell opencode-sessions-export
  workcell opencode-sessions-import

For more information, see README.md
EOF
}

show_run_help() {
    cat << 'EOF'
Run the Agent Workcell in the current directory

Usage:
  workcell run <agent> [options] [-- agent-args]

Agents:
  claude     Launch Claude Code
  opencode   Launch opencode
  codex      Launch Codex
  pi         Launch Pi

Options:
  --yolo            Enable YOLO mode (no permission prompts)
                    claude:   passes --dangerously-skip-permissions
                    opencode: injects {"permission":"allow"} via
                              OPENCODE_CONFIG_CONTENT
                    codex:    passes --dangerously-bypass-approvals-and-sandbox
                    pi:       no extra flag; container is the permission boundary
  --firewalled      Restrict network to essential domains only
  --with-chrome     Start Chrome with remote debugging
  --with-flutter    Start Flutter host bridge
                    Mutually exclusive with --with-chrome
  --bridge-port <port>
                    Select Flutter bridge port when used with --with-flutter
  --flutter-project-dir <dir>
                    Flutter project directory relative to the workspace
                    when used with --with-flutter
  --port <port>     Expose a dev-server port to the host (repeatable)

Examples:
  workcell run claude --yolo
  workcell run opencode --yolo
  workcell run codex --yolo
  workcell run pi
  workcell run claude --yolo --with-chrome --port 3000
  workcell run codex --with-flutter --bridge-port 8765
  workcell run codex --with-flutter --flutter-project-dir ./gui
  workcell run codex --with-flutter --bridge-port 8766 --port 3000
  workcell run opencode --port 3000 --port 5173
  workcell run codex --yolo --port 3000
EOF
}

show_build_help() {
    cat << 'EOF'
Build or rebuild Agent Workcell Docker images

Usage:
  workcell build [all|claude|opencode|codex|pi] [docker-compose-build-args]

Examples:
  workcell build
  workcell build all
  workcell build codex --no-cache

Notes:
  Runs `docker compose build` from the workcell repository root. The shared
  base image is built before targeted agent images.
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
  workcell start-chrome [options]

Options:
  --port <port>       Override debug port from config
  --profile <name>    Override Chrome profile from config
  --restart, -r       Kill running Chrome and restart with debugging

Examples:
  workcell start-chrome
  workcell start-chrome --restart
  workcell start-chrome --port 9333 --profile "Profile 1"

Note: Chrome must not be running, or use --restart to auto-restart it.
EOF
}

show_start_flutter_bridge_help() {
    cat << 'EOF'
Start Flutter bridge for sandbox connection

Usage:
  workcell start-flutter-bridge [options]

Options:
  --port <port>         Override bridge port from config
  --project <dir>       Override Flutter project directory
  --flutter-project-dir <dir>
                       Flutter project directory relative to the workspace
  --target <file>       Override Flutter target file
  --token <token>       Specify bridge bearer token

Examples:
  workcell start-flutter-bridge
  workcell start-flutter-bridge --port 8766 --project ~/my-flutter-app
  workcell start-flutter-bridge --flutter-project-dir ./gui

The bridge exposes an HTTP API on the configured port. The sandbox
connects via host.docker.internal using the bearer token for auth. Agents
choose the Flutter target with `flutterctl devices` and
`flutterctl launch --device <id>`.
EOF
}

# Parse command
command="${1:-}"

case "$command" in
    "")
        show_help
        echo ""
        echo "Error: command is required. To launch an agent, use: workcell run <agent>"
        exit 1
        ;;

    build)
        shift

        if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
            show_build_help
            exit 0
        fi

        target="${1:-all}"
        if [[ "$target" == "all" || "$target" == "claude" || "$target" == "opencode" || "$target" == "codex" || "$target" == "pi" ]]; then
            shift || true
        else
            target="all"
        fi

        ensure_docker_running
        cd "$SCRIPT_DIR"
        docker compose build "$@" agent-workcell-base
        if [[ "$target" == "all" ]]; then
            exec docker compose build "$@" agent-workcell-claude agent-workcell-opencode agent-workcell-codex agent-workcell-pi
        else
            exec docker compose build "$@" "agent-workcell-$target"
        fi
        ;;

    run)
        shift

        if [[ "$1" == "--help" || "$1" == "-h" ]]; then
            show_run_help
            exit 0
        fi

        if [ -z "${1:-}" ]; then
            echo "Error: agent is required (expected 'claude', 'opencode', 'codex', or 'pi')"
            echo "Usage: workcell run <agent> [options] [-- agent-args]"
            exit 1
        fi

        case "$1" in
            claude|opencode|codex|pi) ;;
            -*)
                echo "Error: agent is required before options (expected 'claude', 'opencode', 'codex', or 'pi')"
                echo "Usage: workcell run <agent> [options] [-- agent-args]"
                exit 1
                ;;
            *)
                echo "Error: unknown agent '$1' (expected 'claude', 'opencode', 'codex', or 'pi')"
                exit 1
                ;;
        esac

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

    start-flutter-bridge)
        shift

        if [[ "$1" == "--help" || "$1" == "-h" ]]; then
            show_start_flutter_bridge_help
            exit 0
        fi

        exec "$SCRIPT_DIR/scripts/start-flutter-bridge.sh" "$@"
        ;;

    gpg-new)
        shift
        if [[ "$1" == "--help" || "$1" == "-h" ]]; then
            echo "Generate a new sandbox GPG key"
            echo ""
            echo "Usage:"
            echo "  workcell gpg-new"
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
        existing=$(docker run --rm --entrypoint bash -v "${WORKCELL_SHARED_GPG_VOLUME_NAME}:/data/.gnupg" "$WORKCELL_BASE_IMAGE_NAME" \
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
            docker run --rm --entrypoint bash -v "${WORKCELL_SHARED_GPG_VOLUME_NAME}:/data/.gnupg" "$WORKCELL_BASE_IMAGE_NAME" \
                -c 'rm -rf /data/.gnupg/*'
        fi

        echo "Generating GPG signing key for $GIT_AUTHOR_NAME <$GIT_AUTHOR_EMAIL>..."
        docker run --rm --entrypoint bash -v "${WORKCELL_SHARED_GPG_VOLUME_NAME}:/data/.gnupg" \
            -e "GIT_AUTHOR_NAME=$GIT_AUTHOR_NAME" \
            -e "GIT_AUTHOR_EMAIL=$GIT_AUTHOR_EMAIL" \
            "$WORKCELL_BASE_IMAGE_NAME" \
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
                    echo "  workcell gpg-export --file <path>"
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
            echo "Usage: workcell gpg-export --file <path>"
            exit 1
        fi

        ensure_docker_running
        docker run --rm --entrypoint bash -v "${WORKCELL_SHARED_GPG_VOLUME_NAME}:/data/.gnupg" "$WORKCELL_BASE_IMAGE_NAME" \
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
                    echo "  workcell gpg-import --file <key-file>"
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
            echo "Usage: workcell gpg-import --file <key-file>"
            exit 1
        fi

        if [ ! -f "$infile" ]; then
            echo "Error: File not found: $infile"
            exit 1
        fi

        ensure_docker_running
        docker run --rm -i --entrypoint bash -v "${WORKCELL_SHARED_GPG_VOLUME_NAME}:/data/.gnupg" "$WORKCELL_BASE_IMAGE_NAME" \
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
                    echo "  workcell gpg-revoke --file <path>"
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
            echo "Usage: workcell gpg-revoke --file <path>"
            exit 1
        fi

        ensure_docker_running
        # Resolve to absolute path and mount the parent directory
        outdir="$(cd "$(dirname "$outfile")" && pwd)"
        outname="$(basename "$outfile")"

        docker run --rm -it --entrypoint bash \
            -v "${WORKCELL_SHARED_GPG_VOLUME_NAME}:/data/.gnupg" \
            -v "$outdir:/output" \
            -e "OUTNAME=$outname" \
            "$WORKCELL_BASE_IMAGE_NAME" \
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
            echo "  workcell gpg-erase"
            echo ""
            echo "This permanently deletes all GPG keys from the sandbox volume."
            echo "A new key will be generated on the next launch if GPG_SIGNING is enabled."
            exit 0
        fi

        read -r -p "This will permanently delete all GPG keys from the sandbox. Continue? [y/N] " confirm
        case "$confirm" in
            y|Y)
                ensure_docker_running
                docker run --rm --entrypoint bash -v "${WORKCELL_SHARED_GPG_VOLUME_NAME}:/data/.gnupg" "$WORKCELL_BASE_IMAGE_NAME" \
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
            echo "Open a shell in a workcell Docker volume"
            echo ""
            echo "Usage:"
            echo "  workcell volume-shell <claude|opencode|codex|pi|gpg>"
            exit 0
        fi
        scope="${1:-}"
        case "$scope" in
            claude|opencode|codex|pi) volume="$(agent_volume_name "$scope")" ;;
            gpg) volume="$WORKCELL_SHARED_GPG_VOLUME_NAME" ;;
            *) echo "Error: scope is required (expected 'claude', 'opencode', 'codex', 'pi', or 'gpg')"; exit 1 ;;
        esac
        ensure_docker_running
        docker run --rm -it -v "${volume}:/data" -w /data alpine sh
        ;;

    volume-backup)
        shift
        outfile=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --file) outfile="$2"; shift 2 ;;
                --help|-h)
                    echo "Backup all workcell volumes to a file"
                    echo "Usage: workcell volume-backup --file <path.tgz>"
                    echo "Includes claude, opencode, codex, pi, and shared gpg volumes."
                    exit 0 ;;
                *) echo "Unknown option: $1"; exit 1 ;;
            esac
        done
        [ -n "$outfile" ] || { echo "Error: --file is required"; exit 1; }
        ensure_docker_running
        outdir="$(cd "$(dirname "$outfile")" && pwd)"
        outname="$(basename "$outfile")"
        docker run --rm             -v "$(agent_volume_name claude):/volumes/claude:ro"             -v "$(agent_volume_name opencode):/volumes/opencode:ro"             -v "$(agent_volume_name codex):/volumes/codex:ro"             -v "$(agent_volume_name pi):/volumes/pi:ro"             -v "${WORKCELL_SHARED_GPG_VOLUME_NAME}:/volumes/gpg:ro"             -v "$outdir:/backup" alpine             tar -czf "/backup/$outname" -C /volumes .
        echo "Volumes backed up to: $outfile"
        ;;

    volume-restore)
        shift
        infile=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --file) infile="$2"; shift 2 ;;
                --help|-h)
                    echo "Restore all workcell volumes from a backup"
                    echo "Usage: workcell volume-restore --file <path.tgz>"
                    echo "WARNING: This replaces claude, opencode, codex, pi, and shared gpg volume contents."
                    exit 0 ;;
                *) echo "Unknown option: $1"; exit 1 ;;
            esac
        done
        [ -n "$infile" ] || { echo "Error: --file is required"; exit 1; }
        [ -f "$infile" ] || { echo "Error: File not found: $infile"; exit 1; }
        read -r -p "This will replace all workcell volume contents. Type 'all' to continue: " confirm
        [ "$confirm" = "all" ] || { echo "Aborted."; exit 0; }
        ensure_docker_running
        indir="$(cd "$(dirname "$infile")" && pwd)"
        inname="$(basename "$infile")"
        docker run --rm             -v "$(agent_volume_name claude):/volumes/claude"             -v "$(agent_volume_name opencode):/volumes/opencode"             -v "$(agent_volume_name codex):/volumes/codex"             -v "$(agent_volume_name pi):/volumes/pi"             -v "${WORKCELL_SHARED_GPG_VOLUME_NAME}:/volumes/gpg"             -v "$indir:/backup:ro" alpine             sh -c 'for d in /volumes/*; do rm -rf "$d"/* "$d"/.[!.]* "$d"/..?* 2>/dev/null || true; done; tar -xzf "/backup/$0" -C /volumes' "$inname"
        echo "Volumes restored from: $infile"
        ;;

    volume-rm)
        shift
        if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
            echo "Remove workcell Docker volumes"
            echo "Usage: workcell volume-rm <claude|opencode|codex|pi|gpg|all>"
            exit 0
        fi
        scope="${1:-}"
        case "$scope" in
            claude|opencode|codex|pi) volumes=("$(agent_volume_name "$scope")") ;;
            gpg) volumes=("$WORKCELL_SHARED_GPG_VOLUME_NAME") ;;
            all) volumes=("$(agent_volume_name claude)" "$(agent_volume_name opencode)" "$(agent_volume_name codex)" "$(agent_volume_name pi)" "$WORKCELL_SHARED_GPG_VOLUME_NAME") ;;
            *) echo "Error: scope is required (expected 'claude', 'opencode', 'codex', 'pi', 'gpg', or 'all')"; exit 1 ;;
        esac
        read -r -p "This will permanently delete volume scope '$scope'. Type '$scope' to continue: " confirm
        [ "$confirm" = "$scope" ] || { echo "Aborted."; exit 0; }
        ensure_docker_running
        docker volume rm "${volumes[@]}"
        echo "Removed volume scope '$scope'."
        ;;

    settings)
        shift
        if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
            echo "Open an agent's config file in vi (inside the sandbox volume)"
            echo ""
            echo "Usage:"
            echo "  workcell settings <agent>"
            echo ""
            echo "Agents (required):"
            echo "  claude    ~/.claude/settings.json"
            echo "  opencode  ~/.config/opencode/opencode.jsonc (preferred if it exists)"
            echo "            ~/.config/opencode/opencode.json"
            echo "  codex     ~/.codex/config.toml"
            echo "  pi        ~/.pi/agent/settings.json"
            exit 0
        fi

        if [ -z "${1:-}" ]; then
            echo "Error: agent is required (expected 'claude', 'opencode', 'codex', or 'pi')"
            echo "Usage: workcell settings <agent>"
            exit 1
        fi

        settings_agent="$1"
        if ! valid_agent "$settings_agent"; then
            echo "Error: unknown agent '$settings_agent' (expected 'claude', 'opencode', 'codex', or 'pi')"
            exit 1
        fi
        settings_volume="$(agent_volume_name "$settings_agent")"
        settings_image="$(agent_image_name "$settings_agent")"
        ensure_docker_running
        case "$settings_agent" in
            claude)
                docker run --rm -it --entrypoint sh -v "${settings_volume}:/data" -v "${WORKCELL_SHARED_GPG_VOLUME_NAME}:/data/.gnupg" "$settings_image" -lc '
                    mkdir -p /data/.claude
                    chown -R agent:agent /data/.claude
                    [ -f /data/.claude/settings.json ] || printf "{}\n" > /data/.claude/settings.json
                    chown agent:agent /data/.claude/settings.json
                    exec runuser -u agent -- vi /data/.claude/settings.json
                '
                ;;
            opencode)
                docker run --rm -it --entrypoint sh -v "${settings_volume}:/data" -v "${WORKCELL_SHARED_GPG_VOLUME_NAME}:/data/.gnupg" "$settings_image" -lc '
                    mkdir -p /data/.config/opencode
                    chown -R agent:agent /data/.config/opencode
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
                    chown agent:agent "$settings_path"
                    exec runuser -u agent -- vi "$settings_path"
                '
                ;;
            codex)
                docker run --rm -it --entrypoint sh -v "${settings_volume}:/data" -v "${WORKCELL_SHARED_GPG_VOLUME_NAME}:/data/.gnupg" "$settings_image" -lc '
                    mkdir -p /data/.codex
                    chown -R agent:agent /data/.codex
                    settings_path=/data/.codex/config.toml
                    if [ ! -f "$settings_path" ]; then
                        printf "# Codex user configuration\n" > "$settings_path"
                    fi
                    chown agent:agent "$settings_path"
                    exec runuser -u agent -- vi "$settings_path"
                '
                ;;
            pi)
                docker run --rm -it --entrypoint sh -v "${settings_volume}:/data" -v "${WORKCELL_SHARED_GPG_VOLUME_NAME}:/data/.gnupg" "$settings_image" -lc '
                    mkdir -p /data/.pi/agent
                    chown -R agent:agent /data/.pi
                    settings_path=/data/.pi/agent/settings.json
                    if [ ! -f "$settings_path" ]; then
                        printf "{}\n" > "$settings_path"
                    fi
                    chown agent:agent "$settings_path"
                    exec runuser -u agent -- vi "$settings_path"
                '
                ;;
        esac
        ;;

    opencode-sessions-export)
        shift
        if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
            echo "Export opencode sessions for the current workspace to a local backup"
            echo ""
            echo "Usage:"
            echo "  workcell opencode-sessions-export"
            echo ""
            echo "Writes one JSON file per session (keyed by session ID) to"
            echo ".workcell/opencode-sessions/ in the current workspace."
            echo ""
            echo "Sessions are auto-scoped to the current workspace: opencode derives"
            echo "the project ID from the git root-commit SHA, or uses \"global\" for"
            echo "non-git directories. Existing files are overwritten; stale files from"
            echo "sessions deleted in opencode are left in place as recovery artifacts."
            exit 0
        fi

        ensure_docker_running
        project_name="${PWD##*/}"
        output_dir="$(pwd)/.workcell/opencode-sessions"
        mkdir -p "$output_dir"

        # Use --user agent to write as uid 1000 (matches volume ownership).
        # Bypasses the entrypoint — image-time symlinks already point the
        # opencode data dirs at /home/agent/persist, so mounting the volume
        # is enough for opencode to see this workspace's sessions.
        docker run --rm --entrypoint sh \
            --user agent \
            -e HOME=/home/agent \
            -v "$(agent_volume_name opencode):/home/agent/persist" \
            -v "${WORKCELL_SHARED_GPG_VOLUME_NAME}:/home/agent/persist/.gnupg" \
            -v "$(pwd):/workspaces/${project_name}" \
            -w "/workspaces/${project_name}" \
            "$(agent_image_name opencode)" -c '
                set -e
                export PATH="/home/agent/.local/bin:$PATH"
                ids=$(opencode session list --format json 2>/dev/null | jq -r ".[].id")
                if [ -z "$ids" ]; then
                    echo "No opencode sessions found for this workspace."
                    exit 0
                fi
                count=0
                for id in $ids; do
                    opencode export "$id" > ".workcell/opencode-sessions/$id.json"
                    count=$((count + 1))
                done
                echo "Exported $count session(s) to .workcell/opencode-sessions/"
            '
        ;;

    opencode-sessions-import)
        shift
        if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
            echo "Import opencode sessions from a workspace backup"
            echo ""
            echo "Usage:"
            echo "  workcell opencode-sessions-import"
            echo ""
            echo "Imports every .json file under .workcell/opencode-sessions/"
            echo "back into opencode's session store. Session IDs and project"
            echo "scoping are preserved from the JSON, so sessions restore to"
            echo "their original workspace as long as the git root-commit SHA"
            echo "matches (or for non-git dirs, as long as projectID is \"global\")."
            echo "Re-importing an existing session is a no-op."
            exit 0
        fi

        ensure_docker_running
        project_name="${PWD##*/}"
        input_dir="$(pwd)/.workcell/opencode-sessions"
        if [ ! -d "$input_dir" ] || [ -z "$(ls -A "$input_dir"/*.json 2>/dev/null)" ]; then
            echo "No session files found in .workcell/opencode-sessions/"
            exit 0
        fi

        docker run --rm --entrypoint sh \
            --user agent \
            -e HOME=/home/agent \
            -v "$(agent_volume_name opencode):/home/agent/persist" \
            -v "${WORKCELL_SHARED_GPG_VOLUME_NAME}:/home/agent/persist/.gnupg" \
            -v "$(pwd):/workspaces/${project_name}" \
            -w "/workspaces/${project_name}" \
            "$(agent_image_name opencode)" -c '
                set -e
                export PATH="/home/agent/.local/bin:$PATH"
                count=0
                for f in .workcell/opencode-sessions/*.json; do
                    [ -e "$f" ] || continue
                    opencode import "$f" >/dev/null
                    count=$((count + 1))
                done
                echo "Imported $count session(s) from .workcell/opencode-sessions/"
            '
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
