# agent workcell

An opinionated, containerized environment for running TUI coding agents in YOLO mode, with
Chrome and Flutter integrations, selective persistence, and isolated GPG-signed commits.

Supports [Claude Code](https://claude.ai/code), [OpenCode](https://opencode.ai/),
[Codex](https://github.com/openai/codex), and [Pi](https://pi.dev/), selectable per launch. It is
geared toward Rust, Python, TypeScript, and Dart/Flutter development. A global context file is
seeded into each agent config on first use so the agent is aware of the sandbox's capabilities
and constraints; persisted user edits are preserved.

## Documentation

- [Chrome integration](docs/chrome-integration.md) - host Chrome control for web development.
- [Flutter integration](docs/flutter-integration.md) - in-container SDK and host bridge for
  native/device Flutter work.
- [GPG setup](docs/gpg-setup.md) - verified Git commits from inside the workcell.

## Prerequisites

- Docker installed
- macOS, Linux, or WSL2

Optional integrations have their own host requirements:

- Chrome integration requires Google Chrome and `socat`.
- Flutter bridge integration requires the Flutter SDK and at least one configured target on the host.
- GPG signing requires `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, and `GPG_SIGNING=true` in `config.sh`.

## Setup

### 1. Add the shell alias

Add this to your `~/.zshrc`:

```bash
alias workcell="/path/to/agent-workcell/cli.sh"
```

Replace `/path/to/agent-workcell` with the actual path to this repository, then reload your shell:

```bash
source ~/.zshrc
```

### 2. Run an agent

Run the workcell with a selected agent to build its sandbox image on demand:

```bash
workcell opencode run
```

See [Run Agents](#run-agents) below for the other agent commands. Each harness has its own native
authentication flow when credentials are needed.

### 3. Configure optional integrations

Copy the config template before enabling optional integrations:

```bash
cp config.template.sh config.sh
```

Then follow the focused setup guide you need:

- [Chrome integration](docs/chrome-integration.md)
- [Flutter integration](docs/flutter-integration.md)
- [GPG setup](docs/gpg-setup.md)

`config.sh` is gitignored so personal paths, ports, and identities are not committed.

## Command Reference

### Build

```bash
# Build all agent images
workcell build

# Or build one agent image plus the shared base
workcell pi build
```

`workcell build` runs `docker compose build` from the workcell repository root, so it works even
when you invoke `workcell` from another directory, and builds all four agent images plus the
shared base. To build a single agent, use the harness subcommand form:
`workcell <agent> build` where agent is `claude`, `opencode`, `codex`, or `pi`.

### Run Agents

Navigate to any project directory and run:

```bash
# Normal mode
workcell claude run
workcell opencode run
workcell codex run
workcell pi run  # Pi does not use permission prompts by default

# YOLO mode (no permission prompts)
workcell claude run --yolo
workcell opencode run --yolo
workcell codex run --yolo

# Firewalled mode (restricted network access)
workcell codex run --firewalled

# With a prompt
workcell claude run --yolo -- -p "fix the tests"

# Pass agent-specific arguments after --
workcell claude run -- --resume
workcell opencode run -- run "summarize the repo"
workcell codex run -- "fix the tests"
workcell pi run -- -p "summarize the repo"
```

The agent is the first positional argument and is required: `claude`, `opencode`, `codex`, or
`pi`. Each agent uses its own sandbox image and persistent Docker volume, plus a shared GPG
volume. If the selected image is missing, `workcell <agent> run` builds that agent image and the
shared base automatically.

`--with-chrome` and `--with-flutter` are mutually exclusive. `--port` exposes container dev
servers to the host in all modes. In Flutter mode, use `--bridge-port` to select the host Flutter
bridge port. If the Flutter project is in a workspace subdirectory, pass
`--flutter-project-dir ./gui`.

`--yolo` maps to each agent's native bypass where one exists:

- **claude**: `--dangerously-skip-permissions`
- **opencode**: `{"permission":"allow"}` injected through `OPENCODE_CONFIG_CONTENT`
- **codex**: `--dangerously-bypass-approvals-and-sandbox`
- **pi**: ignored because Pi does not ask for permissions by default; the container is the
  permission boundary

Running `workcell` or `workcell <agent>` without a subcommand exits with a usage error instead of
choosing an agent implicitly.

```bash
workcell codex run --yolo
```

See [Integrations](#integrations) for Chrome, Flutter, and port examples.

### Integrations

```bash
# Chrome enabled for web development
workcell claude run --with-chrome
workcell codex run --yolo --with-chrome --port 3000

# Expose container dev-server ports to the host
workcell opencode run --port 3000
workcell codex run --port 3000 --port 5173

# Start Chrome independently on the host
workcell start-chrome
workcell start-chrome --restart
workcell start-chrome --port 9333 --profile "Profile 1"

# Flutter native/device bridge
workcell claude run --with-flutter
workcell codex run --with-flutter --bridge-port 8765
workcell codex run --with-flutter --flutter-project-dir ./gui
workcell codex run --with-flutter --bridge-port 8766 --port 3000

# Start the Flutter bridge independently on the host
workcell start-flutter-bridge
workcell start-flutter-bridge --port 8766 --project ~/my-flutter-app
workcell start-flutter-bridge --flutter-project-dir ./gui
```

See [Chrome integration](docs/chrome-integration.md) and
[Flutter integration](docs/flutter-integration.md) for setup details.

### Settings, Context, and Skills

```bash
workcell claude settings
workcell opencode settings
workcell codex settings
workcell pi settings

workcell claude context open
workcell opencode context open
workcell codex context open
workcell pi context open
workcell claude context restore

workcell claude skill list
workcell opencode skill list
workcell codex skill list
workcell pi skill list
workcell claude skill open chrome-integration
workcell claude skill restore chrome-integration
```

The `settings` commands open an agent's config file in `vi` inside the workcell Docker volume.
The `context open` command opens the in-effect global context source and prints its exact path.
Harness-native context paths are symlinks: Claude uses `~/.claude/CLAUDE.md`; OpenCode, Codex,
and Pi use `AGENTS.md`. Without a configured shared context repo, those symlinks point to
persisted `workcell-context.md` files seeded from the image default `/opt/agent-context.md`
(`sandbox/DEFAULT_AGENTS.md`). With a shared context repo and `GLOBAL_AGENTS.md` present, the
native paths point to the repo file instead. Use `context restore` to restore the in-effect source
from the image default after an interactive `y/N` confirmation; if the repo file is in effect,
this overwrites the shared repo file.

The `skill list` command shows effective global skills with `NAME`, `LOCATION`, and `PATH`, plus a
separate `Shadowed:` section when a mounted repo skill hides a sandbox-volume skill of the same
name. Baked default skills are seeded into persisted `workcell-skills` directories and are used as
restore sources. Harness-native `skills/` paths are symlinks to ephemeral merged views under
`/tmp/workcell-merged-skills`; do not edit or create files directly in those merged views. Use
`skill open <name>` to open the real in-effect source. If the skill does not exist, it creates a
new skill in the mounted context repo when configured, otherwise in the sandbox-volume
`workcell-skills` source. Use `skill restore <name>` to replace an in-effect default skill's entire
real source directory from the baked image default after confirmation; custom skills must be
recovered via Git or manual edits.

#### Optional shared context repo

Set `WORKCELL_CONTEXT_REPO` in repository-root `config.sh` to an absolute host directory path:

```bash
WORKCELL_CONTEXT_REPO="/Users/you/agent-context"
```

This is only read from `config.sh`; shell environment variables and `.workcell/.env` are not
supported for this setting. The directory is mounted writable at `/opt/workcell-context`. Supported
layout is intentionally limited to:

```text
agent-context/
├── GLOBAL_AGENTS.md
└── skills/
    └── <skill-name>/SKILL.md
```

`GLOBAL_AGENTS.md` is optional; create it manually in the repo when you want repo global context to
take effect. `skills/` is optional; repo skills take precedence over sandbox-volume skills by skill
name, and non-conflicting sandbox-volume skills remain visible. `prompts/` is not supported;
model reusable prompts or workflows as skills.

The context repo is user-managed and should usually be tracked in Git. Repo context and skill edits
from the sandbox write back to the host repo when the user explicitly asks for them, and can affect
all harnesses/workspaces using that repo. Host permissions must allow the container `agent` user to
write if `context open`, `context restore`, `skill open`, or `skill restore` should modify repo
files.

| Harness | Native context | Persisted context source | Native skills | Persisted skill source |
|---------|----------------|--------------------------|---------------|------------------------|
| Claude | `~/.claude/CLAUDE.md` | `~/.claude/workcell-context.md` | `~/.claude/skills` | `~/.claude/workcell-skills` |
| OpenCode | `~/.config/opencode/AGENTS.md` | `~/.config/opencode/workcell-context.md` | `~/.config/opencode/skills` | `~/.config/opencode/workcell-skills` |
| Codex | `~/.codex/AGENTS.md` | `~/.codex/workcell-context.md` | `~/.agents/skills` | `~/.agents/workcell-skills` |
| Pi | `~/.pi/agent/AGENTS.md` | `~/.pi/agent/workcell-context.md` | `~/.pi/agent/skills` | `~/.pi/agent/workcell-skills` |

Project-scoped skills are usually preferable; create global skills only when explicitly asking for
a reusable global skill.

#### One-time manual migration for existing volumes

Workcell now expects native context and skill paths to be symlinks. If an old real context file or
real native `skills/` directory remains, startup fails with a message asking you to run the manual
migration. Run the relevant host command before launching that harness. These commands refuse to
overwrite already-migrated destinations.

```bash
# Claude
docker run --rm -v agent-workcell-claude:/data alpine sh -lc '
set -e
mkdir -p /data/.claude
[ ! -e /data/.claude/workcell-context.md ] || { echo "workcell-context.md exists"; exit 1; }
[ ! -e /data/.claude/workcell-skills ] || { echo "workcell-skills exists"; exit 1; }
[ -f /data/.claude/CLAUDE.md ] && mv /data/.claude/CLAUDE.md /data/.claude/workcell-context.md || true
[ -d /data/.claude/skills ] && mv /data/.claude/skills /data/.claude/workcell-skills || true
'

# OpenCode
docker run --rm -v agent-workcell-opencode:/data alpine sh -lc '
set -e
mkdir -p /data/.config/opencode
[ ! -e /data/.config/opencode/workcell-context.md ] || { echo "workcell-context.md exists"; exit 1; }
[ ! -e /data/.config/opencode/workcell-skills ] || { echo "workcell-skills exists"; exit 1; }
[ -f /data/.config/opencode/AGENTS.md ] && mv /data/.config/opencode/AGENTS.md /data/.config/opencode/workcell-context.md || true
[ -d /data/.config/opencode/skills ] && mv /data/.config/opencode/skills /data/.config/opencode/workcell-skills || true
'

# Codex (global skills moved from legacy ~/.codex/skills to ~/.agents/workcell-skills)
docker run --rm -v agent-workcell-codex:/data alpine sh -lc '
set -e
mkdir -p /data/.codex /data/.agents
[ ! -e /data/.codex/workcell-context.md ] || { echo "workcell-context.md exists"; exit 1; }
[ ! -e /data/.agents/workcell-skills ] || { echo "workcell-skills exists"; exit 1; }
[ -f /data/.codex/AGENTS.md ] && mv /data/.codex/AGENTS.md /data/.codex/workcell-context.md || true
[ -d /data/.codex/skills ] && mv /data/.codex/skills /data/.agents/workcell-skills || true
'

# Pi
docker run --rm -v agent-workcell-pi:/data alpine sh -lc '
set -e
mkdir -p /data/.pi/agent
[ ! -e /data/.pi/agent/workcell-context.md ] || { echo "workcell-context.md exists"; exit 1; }
[ ! -e /data/.pi/agent/workcell-skills ] || { echo "workcell-skills exists"; exit 1; }
[ -f /data/.pi/agent/AGENTS.md ] && mv /data/.pi/agent/AGENTS.md /data/.pi/agent/workcell-context.md || true
[ -d /data/.pi/agent/skills ] && mv /data/.pi/agent/skills /data/.pi/agent/workcell-skills || true
'
```

### GPG Keys

```bash
workcell gpg new
workcell gpg export --file my-key-backup.asc
workcell gpg import --file my-key-backup.asc
workcell gpg revoke --file revoke.asc
workcell gpg erase
```

See [GPG setup](docs/gpg-setup.md) for key setup, backup, and rotation guidance.

### OpenCode Sessions

```bash
workcell opencode sessions export
workcell opencode sessions import
```

These commands export and import OpenCode sessions between the Docker volume and
`.workcell/opencode-sessions/`.

### Volume Management

```bash
# Open a shell in a specific volume
workcell volume shell codex
workcell volume shell gpg

# Backup all workcell volumes
workcell volume backup --file agent-workcell-bkp.tgz

# Restore all workcell volumes from backup
workcell volume restore --file agent-workcell-bkp.tgz

# Remove a specific volume scope, or all scopes
workcell volume rm codex
workcell volume rm all
```

Volume commands affect the persisted user data described below.

## How It Works

- Your current directory is mounted at `/workspaces/<project-name>` inside the container.
- Workspace-local workcell files for the current project live under `.workcell/`.
- Claude session history for the project is stored in `.workcell/claude-sessions/`.
- OpenCode session history and storage persist in the Docker volume under
  `~/.local/share/opencode/`.
- Codex auth, config, history, logs, and session data persist under `~/.codex/`, with project
  conversation files bind-mounted into `.workcell/codex-sessions/`.
- Pi auth, settings, packages/extensions, and the persisted Pi install prefix live in the Docker
  volume under `~/.pi/agent/`, with project sessions bind-mounted into `.workcell/pi-sessions/`.
- Agent settings, credentials, Rust toolchains, Node versions, and language caches persist in the
  selected agent's Docker volume (`agent-workcell-claude`, `agent-workcell-opencode`,
  `agent-workcell-codex`, or `agent-workcell-pi`).
- GPG keys persist in the shared `agent-workcell-gpg` Docker volume.
- The container runs as a non-root `agent` user.
- Filesystem access is isolated to the mounted project directory.
- Host services are reachable from the container through `host.docker.internal`.
- Dev server ports can be exposed with `--port <port>`.
- `/opt/agent-context.md` is the image default used to seed persisted context files when they
  are absent: `~/.claude/CLAUDE.md`, `~/.config/opencode/AGENTS.md`, `~/.codex/AGENTS.md`,
  and `~/.pi/agent/AGENTS.md`. Existing persisted context files are never overwritten. Default
  Chrome integration and Flutter integration workflow skills are seeded into each harness's global
  skills directory only when absent; user edits and user-added skills are preserved.

## Persistence

User-level data is split across per-agent Docker volumes. The selected agent volume is mounted at
`/home/agent/persist` inside the container, and the shared GPG volume is mounted at
`/home/agent/persist/.gnupg`.

Volumes:

- `agent-workcell-claude`
- `agent-workcell-opencode`
- `agent-workcell-codex`
- `agent-workcell-pi`
- `agent-workcell-gpg` (shared signing keys only)

Important persisted paths include:

- `~/.claude/` - Claude Code credentials, settings, global context, and global skills.
- `~/.config/opencode/` - OpenCode configuration, global context, and global skills.
- `~/.local/state/opencode/` - OpenCode local UI state.
- `~/.local/share/opencode/` - OpenCode auth, logs, database, and storage.
- `~/.codex/` - Codex auth, config, history, logs, global context, and global skills.
- `~/.pi/agent/` - Pi settings, auth, packages/extensions, persisted Pi install prefix, global
  context, and global skills. Current-project Pi sessions are bind-mounted from `.workcell/pi-sessions/`.
- `~/.rustup/` and `~/.cargo/` - Rust toolchains, registry cache, and installed binaries.
- `~/.gnupg/` - GPG keys for commit signing when enabled; stored in `agent-workcell-gpg`.
- `~/.nvm/` - Node.js versions and global npm packages.
- `~/.flutter/` - Flutter CLI config and version state.
- `~/.pub-cache/` - Dart pub package cache shared across projects.

Image-owned tool binaries and SDKs, including Flutter under `/opt/flutter-sdk`, Claude Code
version payloads, OpenCode, the default Pi install under `/opt/pi`, and protobuf CLIs, update with
the sandbox image. The entrypoint sets up symlinks so each tool still sees its expected home
directory paths without using stale persisted binary copies. It seeds the default agent context
and default global skills only when the persisted files are absent, so custom context and skills
survive restarts and image updates. Pi runs on the active nvm Node at
runtime. Pi package/extension updates persist under `~/.pi/agent/`; the entrypoint seeds Pi's
own install prefix under `~/.pi/agent/self/` from the image on first run, so native `pi update`
self-updates write to the persisted volume instead of ephemeral `/opt/pi`. Once a persisted Pi
copy exists, the sandbox keeps using it and leaves further version upgrades to explicit user-run
`pi update` commands.

> **Security note.** Agent credentials are stored as plaintext inside Docker volumes. Treat
> `agent-workcell-*` volumes and their backups as sensitive.

### Workspace-local data

Each project gets a `.workcell/` directory for project-scoped agent state:

- `.workcell/artifacts/` - temporary agent artifacts such as screenshots, logs, traces, and
  generated previews. Agents may create optional subdirectories such as `screenshots/`, `logs/`,
  and `mockups/` when that helps organize related files. Use timestamped filenames such as
  `screenshots/20260429-132400-home-page.png`.
- `.workcell/claude-sessions/` - bind-mounted Claude project sessions.
- `.workcell/opencode-sessions/` - exported OpenCode session backups.
- `.workcell/codex-sessions/` - workspace-local Codex conversation files.
- `.workcell/pi-sessions/` - bind-mounted Pi project sessions.
- `.workcell/.env` - optional workspace-local environment variables to define for sandboxed agents.
- `.workcell/tasks/` - multi-agent task files and scratch notes.
- `.workcell/flutter-config.json` - project-local Flutter bridge launch and connection settings
  when Flutter integration is used.

Example `.workcell/` layout:

```text
.workcell/
├── .gitignore
├── .env
├── artifacts/
│   ├── screenshots/
│   ├── logs/
│   └── mockups/
├── claude-sessions/
├── codex-sessions/
├── opencode-sessions/
├── pi-sessions/
├── tasks/
└── flutter-config.json
```

On first run, the launcher creates `.workcell/.gitignore` if it does not already exist:

```gitignore
.DS_Store
.env
flutter-config.json
artifacts/
```

When `.workcell/.env` exists, `workcell <agent> run` parses it as dotenv-style `KEY=VALUE`
entries and passes the values into the sandboxed agent environment. Blank lines and comments are
ignored, `export KEY=VALUE` is accepted, quoted values are unquoted, and invalid lines stop the
launch with an error. Launcher-controlled variables such as the selected agent, timezone, exposed
ports, and integration settings take precedence over duplicate names in `.workcell/.env`.

It is recommended to gitignore `.workcell/` in the parent project repository. If you want version
control for local agent state, initialize a separate Git repository inside `.workcell/`.

### OpenCode session backup

OpenCode stores its live session database in the Docker volume. Export sessions to workspace-local
JSON files before removing the volume. See [OpenCode sessions](#opencode-sessions).

## Available Tools

| Category | Tools |
|----------|-------|
| **Languages** | Node.js LTS through nvm, Python 3.11, Rust stable |
| **Node.js** | `nvm`, `npm`, `npx` |
| **Agents** | `claude`, `opencode`, `codex`, `pi` |
| **Python** | `pyright`, `ruff`, `playwright`, `matplotlib`, `numpy` |
| **Browser** | Chrome automation support |
| **Flutter SDK** | `flutter`, `dart` — tests, analysis, formatting, pub (in-container, no host setup) |
| **Flutter Bridge** | `flutterctl` — launch, hot-reload, screenshots, and macOS-hosted macOS/iOS Simulator UI automation via host bridge |
| **Protobuf** | `protoc`, `buf`, `protoc-gen-dart`, `protoc-gen-prost`, `grpcurl` |
| **Database** | `psql` |
| **Utilities** | `git`, `curl`, `wget`, `jq`, `yq`, `ripgrep`, `fd` |

## Network Restrictions

Use `--firewalled` to restrict network access to essential agent and tooling domains:

- Anthropic API
- OpenAI / Codex
- OpenCode, including Zen and Go
- Pi
- JavaScript and TypeScript package registries
- Dart and Flutter package registry
- Rust package registries and docs
- GitHub

This reduces the risk of data exfiltration while still allowing agents to fetch docs and install
packages.

## Project Structure

```text
agent-workcell/
├── README.md
├── docs/
│   ├── chrome-integration.md
│   ├── flutter-integration.md
│   └── gpg-setup.md
├── docker-compose.yml
├── cli.sh
├── config.template.sh
├── config.sh
├── scripts/
│   ├── run_sandbox.sh
│   ├── start-chrome-debug.sh
│   ├── start-flutter-bridge.sh
│   └── flutter-bridge.py
└── sandbox/
    ├── DEFAULT_AGENTS.md
    ├── default-skills/
    ├── agent-init/
    │   ├── claude.sh
    │   ├── codex.sh
    │   ├── opencode.sh
    │   └── pi.sh
    ├── dockerfiles/
    │   ├── base.Dockerfile
    │   ├── claude.Dockerfile
    │   ├── codex.Dockerfile
    │   ├── opencode.Dockerfile
    │   └── pi.Dockerfile
    ├── entrypoint.sh
    ├── init-firewall.sh
    ├── browser-tools/
    └── flutter-tools/
```

## License

This project is licensed under the [Apache License, Version 2.0](LICENSE).

## Contribution

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion by
you shall be licensed as Apache-2.0 without any additional terms or conditions.
