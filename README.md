# agent workcell

An opinionated, containerized environment for running TUI coding agents in YOLO mode, with
Chrome and Flutter integrations, selective persistence, and isolated GPG-signed commits.

- Supports [Pi](https://pi.dev/), [OpenCode](https://opencode.ai/),
  [Codex](https://github.com/openai/codex), and [Claude Code](https://claude.ai/code), selectable
  per launch.
- Geared toward Rust, Python, TypeScript, and Dart/Flutter development.
- Seeds global context into each agent config on first use so the agent is aware of the sandbox's
  capabilities and constraints, while preserving persisted user edits.
- Optionally mounts a user-managed shared context repo across harnesses and workspaces.
- Includes project-management-oriented features for workflows that span multiple models or agent
  harnesses.

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

Run the workcell with `pi`, `opencode`, `codex`, or `claude` to build the selected sandbox image
on demand:

```bash
workcell <pi|opencode|codex|claude> run
```

Each harness has its own native authentication flow when credentials are needed. Run
`workcell --help` or see the [CLI reference](docs/cli.md) for more commands and options.

### 3. Configure optional integrations

See the documentation links below for optional Chrome, Flutter, and GPG setup.

## Documentation

- [CLI reference](docs/cli.md) - command examples for running agents, integrations, settings,
  contexts, skills, migrations, and volumes.
- [Context management](docs/context-management.md) - default context seeding, persistence,
  shared context repos, and global skills.
- [GPG setup](docs/gpg-setup.md) - verified Git commits from inside the workcell.
- [Chrome integration](docs/chrome-integration.md) - host Chrome control for web development.
- [Flutter integration](docs/flutter-integration.md) - in-container SDK and host bridge for
  native/device Flutter work.

## How It Works

- Your current directory is mounted at `/workspaces/<project-name>` inside the container.
- Workspace-local workcell files for the current project live under `.workcell/`.
- Pi auth, settings, packages/extensions, and the persisted Pi install prefix live in the Docker
  volume under `~/.pi/agent/`, with project sessions bind-mounted from `.workcell/sessions/pi/`.
- OpenCode session history and storage persist in the Docker volume under
  `~/.local/share/opencode/`.
- Codex auth, config, history, logs, and session data persist under `~/.codex/`, with project
  conversation files bind-mounted from `.workcell/sessions/codex/`.
- Claude session history for the project is stored in `.workcell/sessions/claude/`.
- Agent settings, credentials, Rust toolchains, Node versions, and language caches persist in the
  selected agent's Docker volume (`agent-workcell-pi`, `agent-workcell-opencode`,
  `agent-workcell-codex`, or `agent-workcell-claude`).
- GPG keys persist in the shared `agent-workcell-gpg` Docker volume.
- The container runs as a non-root `agent` user.
- Filesystem access is isolated to the mounted project directory.
- Host services are reachable from the container through `host.docker.internal`.
- Dev server ports can be exposed with `--port <port>`.
- `/opt/agent-context.md` is the image default used to seed persisted context files when they
  are absent: `~/.pi/agent/AGENTS.md`, `~/.config/opencode/AGENTS.md`, `~/.codex/AGENTS.md`,
  and `~/.claude/CLAUDE.md`. Existing persisted context files are never overwritten. Default
  Chrome integration, Flutter integration, and project-management workflow skills are seeded into each
  harness's global skills directory only when absent; user edits and user-added skills are preserved.

## Persistence

User-level data is split across per-agent Docker volumes. The selected agent volume is mounted at
`/home/agent/persist` inside the container, and the shared GPG volume is mounted at
`/home/agent/persist/.gnupg`.

Volumes:

- `agent-workcell-pi`
- `agent-workcell-opencode`
- `agent-workcell-codex`
- `agent-workcell-claude`
- `agent-workcell-gpg` (shared signing keys only)

Important persisted paths include:

- `~/.pi/agent/` - Pi settings, auth, packages/extensions, persisted Pi install prefix, global
  context, and global skills. Current-project Pi sessions are bind-mounted from `.workcell/sessions/pi/`.
- `~/.config/opencode/` - OpenCode configuration, global context, and global skills.
- `~/.local/state/opencode/` - OpenCode local UI state.
- `~/.local/share/opencode/` - OpenCode auth, logs, database, and storage.
- `~/.codex/` - Codex auth, config, history, logs, global context, and global skills.
- `~/.claude/` - Claude Code credentials, settings, global context, and global skills.
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

Each project gets an agent-managed `.workcell/` directory for project-scoped state:

- `.workcell/artifacts/` - temporary or heavy agent artifacts.
- `.workcell/sessions/` - project-scoped agent session data.
- `.workcell/.env` - optional workspace-local environment variables for sandboxed agents.
- `.workcell/ideas.md` - possible future improvements.
- `.workcell/roadmap.md` - next-direction items not yet converted into tasks.
- `.workcell/tasks/` - multi-agent task directories.
- `.workcell/flutter-config.json` - Flutter bridge launch and connection settings.

On first run, the launcher creates `.workcell/.gitignore` to keep transient files such as
`.env`, `flutter-config.json`, and `artifacts/` out of version control. It is recommended to
gitignore `.workcell/` in the parent project repository. If you want version control for local
agent state, initialize a separate Git repository inside `.workcell/`.

### OpenCode session backup

OpenCode stores its live session database in the Docker volume. Export sessions to workspace-local
JSON files before removing the volume. See [OpenCode sessions](#opencode-sessions).

## Available Tools

| Category | Tools |
|----------|-------|
| **Languages** | Node.js LTS through nvm, Python 3.11, Rust stable |
| **Node.js** | `nvm`, `npm`, `npx` |
| **Agents** | `pi`, `opencode`, `codex`, `claude` |
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
