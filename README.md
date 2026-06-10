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

- Sandbox-headless browser automation is included in the workcell image.
- Host Chrome integration requires Google Chrome and `socat`.
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
- [Context management](docs/context-management.md) - default context seeding, shared context repos,
  and global skills.
- [Persistence](docs/persistence.md) - host workspace data, per-harness volumes, `.workcell/`,
  shared GPG storage, and backups.
- [GPG setup](docs/gpg-setup.md) - verified Git commits from inside the workcell.
- [Chrome integration](docs/chrome-integration.md) - sandbox-headless browsing and explicit host Chrome control.
- [Flutter integration](docs/flutter-integration.md) - in-container SDK and host bridge for
  native/device Flutter work.

## How It Works

- Only the directory where you run `workcell <agent> run` is mounted into the container at
  `/workspaces/<project-name>`; agents do not get access to all host files.
- Each harness has its own independent persisted Docker volume for auth data, settings, Rust
  toolchains, Node versions, and language caches.
- Project-scoped Pi, Codex, and Claude session data lives under `.workcell/sessions/`. OpenCode
  sessions persist in its harness volume and can be moved through `workcell opencode sessions export`
  and `workcell opencode sessions import`.
- GPG keys persist separately in the shared `agent-workcell-gpg` Docker volume.
- Workcell volumes can be backed up and restored with `workcell volume backup` and
  `workcell volume restore`.
- Host services are reachable from the container through `host.docker.internal`; dev-server ports
  can be exposed to the host with `--port <port>`.
- Default context and global skills are seeded into each harness only when absent, informing agents
  about sandbox tools and constraints while preserving user edits. Use `workcell <agent> context`
  and `workcell <agent> skill` to manage them; an optional shared context repo can be mounted
  across harnesses and workspaces.

## Persistence

Workcell bind-mounts the host workspace and persists Workcell-managed user state in one Docker
volume per agent harness plus a shared GPG volume. Project-scoped `.workcell/` data lives in the
host workspace. Image-owned tools and SDKs update with the sandbox image, while user state in Docker
volumes is preserved across container restarts and image rebuilds.

Use `workcell volume backup` and `workcell volume restore` to back up or restore persisted Docker
volume data. See [Persistence](docs/persistence.md) for the full persistence model, including what
is and is not covered by volume backups.

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

## Available Tools

| Category | Tools |
|----------|-------|
| **Languages** | Node.js LTS through nvm, Python 3.11, Rust stable |
| **Node.js** | `nvm`, `npm`, `npx` |
| **Agents** | `pi`, `opencode`, `codex`, `claude` |
| **Python** | `pyright`, `ruff`, `playwright`, `matplotlib`, `numpy` |
| **Browser** | `browser` CLI with sandbox-headless Chromium and optional host Chrome control |
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
│   ├── cli.md
│   ├── context-management.md
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
│   ├── flutter-bridge.py
│   └── workcell_env.py
├── sandbox/
│   ├── DEFAULT_AGENTS.md
│   ├── default-skills/
│   │   ├── chrome-integration/
│   │   ├── flutter-integration/
│   │   └── project-management/
│   ├── agent-init/
│   │   ├── claude.sh
│   │   ├── codex.sh
│   │   ├── opencode.sh
│   │   └── pi.sh
│   ├── dockerfiles/
│   │   ├── base.Dockerfile
│   │   ├── claude.Dockerfile
│   │   ├── codex.Dockerfile
│   │   ├── opencode.Dockerfile
│   │   └── pi.Dockerfile
│   ├── entrypoint.sh
│   ├── init-firewall.sh
│   ├── browser-tools/
│   └── flutter-tools/
└── tests/
```

## License

This project is licensed under the [Apache License, Version 2.0](LICENSE).

## Contribution

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion by
you shall be licensed as Apache-2.0 without any additional terms or conditions.
