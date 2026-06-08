# Agent Workcell Context

You are running inside an Agent Workcell Docker container. Treat this file as the general sandbox context. Load the focused docs only when the task needs them.

## Global Context And Skills

Load focused workflow skills only when they are relevant to the task.

- For browser-based web development, visual UI checks, dev servers, or the `browser` CLI, use the
  `chrome-integration` skill.
- For native/device Flutter work, host Flutter targets, hot reload, screenshots, or the
  `flutterctl` CLI, use the `flutter-integration` skill.
- For Flutter web, use the Chrome integration workflow, not the native Flutter bridge.

When `/opt/workcell-context` exists, it is a user-managed host-mounted shared context repo. Do not
modify it unless the user explicitly asks you to. Its `GLOBAL_AGENTS.md` (when present) is the
in-effect global context, and its `skills/` entries take precedence over sandbox-volume skills;
changes can affect every harness/workspace using that repo. The harness-visible `skills/` path may
be an ephemeral merged symlink view under `/tmp/workcell-merged-skills`; do not create or edit
skills through that merged view.

Project-scoped skills are usually preferable. Create reusable global skills only when the user
explicitly asks for a global/reusable skill. If a context repo is mounted, create new global skills
in `/opt/workcell-context/skills/<skill-name>/SKILL.md` (creating `skills/` if needed). Otherwise,
create them in the selected harness's persisted source directory:

| Harness | Persisted global skill source |
|---------|-------------------------------|
| Pi | `~/.pi/agent/workcell-skills` |
| OpenCode | `~/.config/opencode/workcell-skills` |
| Codex | `~/.agents/workcell-skills` |
| Claude | `~/.claude/workcell-skills` |

## Host And Sandbox Boundaries

- Use `host.docker.internal` instead of `localhost` when connecting from the container to services running on the host.
- Your current project directory is bind-mounted from the host. File changes in the workspace persist automatically.
- The container runs as a non-root `agent` user for normal agent commands.
- Filesystem access is scoped to the mounted workspace and persisted user data.
- Interactive project scaffolding prompts usually do not work. Prefer non-interactive CLI flags.

## Persistence

Two kinds of data persist between sessions:

1. **Workspace data:** the mounted project directory, including `.workcell/`.
2. **User data:** Docker volume data under `~/persist/`, symlinked into expected home paths.

Project-specific workcell data lives under `.workcell/`:

- `.workcell/artifacts/` - temporary artifacts from agent work, such as screenshots, logs, traces, and generated previews. Agents may create optional subdirectories such as `screenshots/`, `logs/`, and `mockups/` when that helps organize related files. Put throwaway files here instead of the repo root.
- `.workcell/.env` - optional workspace-local environment variables loaded into sandboxed agent sessions. Treat it as secret-bearing and leave it ignored by Git.
- `.workcell/sessions/` - project-scoped agent session data, organized by harness:
  - `.workcell/sessions/pi/` - bind-mounted Pi project sessions when running the Pi harness.
  - `.workcell/sessions/opencode/` - exported OpenCode session backups.
  - `.workcell/sessions/codex/` - workspace-local Codex conversation files when running the Codex harness.
  - `.workcell/sessions/claude/` - bind-mounted Claude project sessions when running the Claude harness.
- `.workcell/tasks/` - shared task notes for multi-step work and handoffs.
- `.workcell/flutter-config.json` - Flutter bridge launch settings and runtime connection details when Flutter integration is used.

Prefer timestamped artifact names so files sort chronologically and avoid collisions. For example:

```text
.workcell/artifacts/screenshots/20260429-132400-home-page.png
.workcell/artifacts/logs/20260429-132405-test-output.txt
.workcell/artifacts/mockups/20260429-132410-dashboard-concept.png
```

Important persisted user paths:

- `~/.nvm/` - Node.js versions and global npm packages for the selected agent volume.
- `~/.rustup/` and `~/.cargo/` - Rust toolchains, registry cache, installed binaries, and config for the selected agent volume.
- `~/.gnupg/` - GPG keys for commit signing when enabled; this is the explicitly shared GPG volume mounted into every agent image.
- `~/.pub-cache/` - Dart pub package cache for the selected agent volume.
- `~/.flutter/` - Flutter CLI config and version state for the selected agent volume.

Each agent harness runs in its own image with its own persisted Docker volume, so other harnesses'
global state paths and binaries are intentionally absent. Depending on the selected harness, the
available persisted harness path is one of:

- `~/.pi/agent/` - Pi settings, auth, packages/extensions, persisted Pi install prefix, and global context (`AGENTS.md`); current-project Pi sessions are bind-mounted from `.workcell/sessions/pi/`.
- `~/.config/opencode/`, `~/.local/share/opencode/`, and `~/.local/state/opencode/` - OpenCode config, global context (`AGENTS.md`), auth, sessions, logs, storage, and local UI state.
- `~/.codex/` - Codex config, auth, history, logs, and global context (`AGENTS.md`); project conversation files are bind-mounted from `.workcell/sessions/codex/`.
- `~/.claude/` - Claude Code credentials, settings, project sessions, and global context (`CLAUDE.md`).

Harness-native context paths are symlinks to the in-effect source: mounted repo
`/opt/workcell-context/GLOBAL_AGENTS.md` when present, otherwise the harness's persisted
`workcell-context.md`. Harness-native skill paths are symlinks to an ephemeral merged view; real
persisted skills live in `workcell-skills` source directories. Codex global skills use
`~/.agents/skills`, with persisted sources in `~/.agents/workcell-skills`.

Installed Node versions, global npm packages, Rust toolchains, and package caches persist across container restarts for the selected agent volume. Image-owned SDKs and the selected agent binary update with that agent's sandbox image. The image default context is seeded into the persisted harness context source file only when that file is absent; existing custom context is never overwritten. Pi package/extension updates persist under `~/.pi/agent/` only in the Pi harness; the entrypoint seeds Pi's own install prefix under `~/.pi/agent/self/` from the image on first run, so native `pi update` self-updates write to the persisted volume instead of ephemeral `/opt/pi`. Once a persisted Pi copy exists, the Pi sandbox keeps using it and leaves further version upgrades to explicit user-run `pi update` commands.

## Ports And Integrations

Check exposed container ports with:

```bash
echo "$EXPOSED_PORTS"
```

If `$EXPOSED_PORTS` is set, dev servers on those ports are reachable from the host at `localhost:<port>`. If a needed port is not exposed, tell the user they can restart the sandbox with `--port <port>`.

`--with-chrome` and `--with-flutter` are mutually exclusive:

- Chrome mode uses `--port` to expose container dev-server ports to host Chrome.
- Flutter mode uses `--bridge-port` to select the host Flutter bridge port; `--port` still exposes container dev-server ports.
- Flutter mode uses `--flutter-project-dir <dir>` when the Flutter project is in a workspace subdirectory such as `./gui`.

## Network Restrictions

Check firewall status with:

```bash
iptables -L OUTPUT -n 2>/dev/null | grep -q "DROP" && echo "Firewall ACTIVE" || echo "Firewall INACTIVE"
```

When the firewall is active, external network access is limited to essential agent and tooling domains:

- Anthropic: `api.anthropic.com`, `claude.ai`, `statsig.anthropic.com`, `sentry.io`
- OpenAI / Codex: `api.openai.com`, `chatgpt.com`, `auth.openai.com`
- OpenCode: `opencode.ai`
- Pi: `pi.dev`
- JavaScript / TypeScript: `registry.npmjs.org`, `npmjs.com`, `yarnpkg.com`, `registry.yarnpkg.com`, `nodejs.org`
- Dart / Flutter: `pub.dev`
- Rust: `crates.io`, `static.crates.io`, `index.crates.io`, `doc.rust-lang.org`, `docs.rs`, `static.rust-lang.org`
- GitHub: `github.com`, `api.github.com`, `raw.githubusercontent.com`, `objects.githubusercontent.com`
- Other: `storage.googleapis.com`

## Available Tools

| Category | Tools |
|----------|-------|
| Languages | Node.js LTS through `nvm`, Python 3.11, Rust stable |
| Node.js | `nvm`, `npm`, `npx` |
| Agent harness | Only the selected harness CLI is installed in this image: `pi`, `opencode`, `codex`, or `claude` |
| Python | `pyright`, `ruff`, `playwright`, `matplotlib`, `numpy` |
| Browser | `browser` CLI for Chrome automation; use the `chrome-integration` skill before browser/web work |
| Flutter | `flutter` and `dart` for tests, analysis, formatting, and pub; `flutterctl` for the host bridge (launch, hot-reload, screenshots); use the `flutter-integration` skill before native Flutter work |
| Protobuf | `protoc`, `buf`, `protoc-gen-dart`, `protoc-gen-prost`, `grpcurl` |
| Database | `psql`; connect to host databases through `host.docker.internal` |
| Utilities | `git`, `curl`, `wget`, `jq`, `yq`, `ripgrep`, `fd` |

## Task Management

Use `.workcell/tasks/` for work that benefits from continuity: multi-step changes, handoffs, research, parallel-agent coordination, risky debugging, or anything likely to span sessions. Skip task files for trivial one-step requests.

Before starting non-trivial work:

1. List `.workcell/tasks/`.
2. Skim task filenames and title lines only. Do not read full task files yet.
3. Ask the user how to track the work: continue a previous task (including likely matches by title when any exist), create a new task, or skip task file creation.
4. Read only the task file the user chooses.
5. Create a new task file only when the user asks for a new one.

Task filenames use UTC timestamp prefixes:

```text
YYYYMMDD-HHMMSS-brief-descriptive-slug.md
```

Inside task files, use local time for logs and metadata. Check the `TZ` environment variable to
determine the configured local timezone, then write the timezone as a compact GMT offset, such as
`GMT-3`, to keep entries short.

Each task file should include:

```markdown
# <Short Title>

- **Status:** pending | in_progress | blocked | completed | cancelled
- **Created:** <YYYY-MM-DD HH:MM GMT-offset>
- **Updated:** <YYYY-MM-DD HH:MM GMT-offset>

## Objective
## Context
## Plan
## Next Steps
## Log

- `<YYYY-MM-DD HH:MM GMT-offset>` | `<author>` | <entry>
  - **CORRECTION** | `<YYYY-MM-DD HH:MM GMT-offset>` | `<author>` | <correction>

## Dependencies
## Notes
```

Keep task files concise and operational. Record decisions, blockers, ownership boundaries, important commands, verification results, and links to artifacts. Put large logs, screenshots, traces, and generated previews in `.workcell/artifacts/` instead of pasting them into the task file.

Keep `Plan` current with succinct notes about what was done and what remains. Add `Log` entries in descending time order, and include the authoring harness/model, such as `codex/gpt-5.5`, when known. If the harness/model is unknown, ask the user; do not infer it from previous log entries. Preserve previous log content. When a correction is needed, add an indented `CORRECTION` entry below the original entry or its previous corrections. Update status, plan checkboxes, and next steps as the task changes. When pausing, leave concrete `Next Steps`. When finished, set `Status` to `completed`, clear `Next Steps`, update `Updated`, and summarize the outcome in `Log`.
