# Persistence

Agent Workcell bind-mounts the host workspace and stores Workcell-managed user state in one Docker
volume per agent harness plus a shared GPG volume. Most tools and SDKs baked into Workcell images are
not user state and update when the sandbox image is rebuilt. Harness CLI installs are a deliberate
exception: they are seeded into the corresponding harness volume so native updates persist.

## Host workspace

The directory where you run `workcell <agent> run` is bind-mounted into the container at:

```text
/workspaces/<project-name>
```

Edits to files in that mounted workspace are host file edits and persist normally. The launcher also
creates or uses a workspace-local `.workcell/` directory for project-scoped agent data such as tasks,
artifacts, sessions, and optional integration config.

Only the current project directory is mounted; agents do not get access to all host files by default.

## Per-harness volumes

Each supported agent has an independent Docker volume:

| Harness | Volume |
|---------|--------|
| Pi | `agent-workcell-pi` |
| OpenCode | `agent-workcell-opencode` |
| Codex | `agent-workcell-codex` |
| Claude | `agent-workcell-claude` |

Inside a running sandbox, the selected harness volume is mounted at:

```text
/home/agent/persist
```

Workcell maps the selected harness's expected home-directory paths into that persisted tree.
Depending on the harness and tools used, this volume stores items such as:

- agent auth data, settings, logs, and harness-native state;
- Workcell-managed global context and global skills;
- language/tool caches such as Node versions, Rust toolchains, Dart pub packages, and Flutter CLI
  state;
- user-installed tools that are installed under persisted home paths;
- harness session data that is not project-scoped.

Common persisted paths visible in sandboxes include:

| Path | Contents |
|------|----------|
| `~/.nvm/` | Node.js versions and global npm packages for the selected harness volume. |
| `~/.rustup/`, `~/.cargo/` | Rust toolchains, registry cache, installed binaries, and Cargo config. |
| `~/.pub-cache/` | Dart and Flutter package cache. |
| `~/.flutter/` | Flutter CLI config and version state. |
| `~/.gnupg/` | GPG home, backed by the shared GPG volume rather than the per-harness volume. |

Harness-specific persisted paths include:

| Harness | Persisted paths and notable contents |
|---------|--------------------------------------|
| Pi | `~/.pi/agent/` for Pi settings, auth, packages/extensions, context, skills, and the persisted Pi self install at `~/.pi/agent/self/`. Project Pi sessions live under `.workcell/sessions/pi/`. |
| OpenCode | `~/.opencode/` for the persisted CLI install; `~/.config/opencode/`, `~/.local/share/opencode/`, and `~/.local/state/opencode/` for settings, auth, logs, sessions, context, and skills. OpenCode project sessions can be exported/imported through `.workcell/sessions/opencode/`. |
| Codex | `~/.codex/packages/standalone/` for the persisted CLI releases and current-release link; the rest of `~/.codex/` for config, auth, history, logs, and context; `~/.agents/` for global skills. Project Codex sessions live under `.workcell/sessions/codex/`. |
| Claude | `~/.local/share/claude/versions/` for persisted CLI versions and `~/.local/share/claude/.workcell-current-version` for Workcell's selected-version record; `~/.claude/` and `~/.claude.json` for credentials, settings, context, skills, and state. Project Claude sessions live under `.workcell/sessions/claude/`. |

Because volumes are per harness, do not assume state from Pi exists in Codex, OpenCode, or Claude,
and vice versa.

## Image-baked tools and volume-backed harness installs

Tools and SDKs baked into Workcell images can change when images are rebuilt. User-managed tool
state under persisted home paths survives container restarts and image rebuilds. For example, Node
versions under `~/.nvm/`, Cargo-installed binaries under `~/.cargo/bin`, and activated Dart packages
under `~/.pub-cache/bin` belong to the selected harness volume.

All four harness CLI installs are also volume-backed:

| Harness | Persistent install root | Native update command |
|---------|-------------------------|-----------------------|
| Pi | `~/.pi/agent/self/` | `pi update --self` |
| OpenCode | `~/.opencode/` | `opencode upgrade --method curl` |
| Codex | `~/.codex/packages/standalone/` | `codex update` |
| Claude | `~/.local/share/claude/` | `claude update` |

The optional Pi-to-cmux notification adapter is different from the Pi CLI install. Workcell owns the
adapter in the Pi image at `/opt/workcell/pi-extensions/terminal-notify.ts` and passes it explicitly
at launch when enabled; it is not copied into `~/.pi/agent/extensions/` and does not modify Pi
settings. Pulling adapter changes therefore requires `workcell pi build`. Rebuilding does not replace
the volume-backed Pi executable, so run `workcell pi update` separately if the persisted Pi version
lacks the extension APIs required by the adapter. Volume backups include the persisted Pi install and
user extensions, but not this image-owned adapter.

On first use, Workcell copies the image-provided harness install into the persistent root only when a
valid persisted executable is absent. After that, the persisted install is authoritative: container
restarts and image rebuilds restore the launcher from the volume and do not replace a valid install
with the image template. Use `workcell <agent> update` to ask the native updater for the newest
policy-allowed release. Update commands do not accept a version argument.

Claude Code can retain multiple installed versions, including a newer binary after a release-channel
downgrade. Workcell therefore records the launcher selected by a successful `claude update` in
`~/.local/share/claude/.workcell-current-version` and restores that version on restart instead of
blindly selecting the highest installed version.

When upgrading an existing Workcell checkout from the older image-owned harness layout, rebuild each
existing harness image once with `workcell <agent> build` to acquire the persistence wiring. Existing
volume state is preserved, and missing persistent installs are seeded non-destructively when the
rebuilt image first starts.

## Project-scoped `.workcell/` data

`.workcell/` lives in the host workspace, not in a harness volume. It is intended for data that
belongs to the project rather than one agent harness, including:

- `.workcell/tasks/` for multi-step task state and handoffs;
- `.workcell/ideas.md` and `.workcell/roadmap.md` when used;
- `.workcell/artifacts/` for temporary or heavy generated outputs;
- `.workcell/sessions/` for project-scoped Pi, Codex, and Claude sessions, plus OpenCode session
  import/export data;
- `.workcell/.env` for optional workspace-local sandbox environment variables;
- `.workcell/flutter-config.json` for Flutter bridge launch/runtime settings.

On first use, Workcell creates `.workcell/.gitignore` to ignore transient files such as `.env`,
`flutter-config.json`, and `artifacts/`. It is usually best to ignore `.workcell/` from the parent
project repository unless you intentionally want to version selected agent state.

## Shared GPG volume

GPG signing keys are stored separately in the shared Docker volume:

```text
agent-workcell-gpg
```

When a sandbox or helper command needs GPG access, this volume is mounted at the expected GPG home
path for that operation. It is shared by all harnesses so commits can use the same signing identity.
Harness update containers do not need signing keys and use an empty temporary GPG home instead of
mounting this volume.

## Shared context repo

When `WORKCELL_CONTEXT_REPO` is configured, Workcell mounts that host directory at:

```text
/opt/workcell-context
```

Its `GLOBAL_AGENTS.md` and `skills/` entries can override per-harness persisted context and skills
across harnesses and workspaces. This repo is user-managed host data and should usually be tracked
or backed up like any other important configuration repository. See
[Context management](context-management.md) for precedence and editing behavior.

## Backups, restore, and inspection

Use the volume commands to inspect or manage Docker-volume state:

```bash
workcell volume shell <pi|opencode|codex|claude|gpg>
workcell volume backup --file agent-workcell-backup.tgz
workcell volume restore --file agent-workcell-backup.tgz
workcell volume rm <pi|opencode|codex|claude|gpg|all>
```

`volume backup` and `volume restore` cover the per-harness volumes—including their harness CLI
installs—and the shared GPG volume. They do not back up host workspace files, `.workcell/`, or a
configured shared context repo; back those up with normal host filesystem or Git workflows.

Removing a harness volume removes its persisted CLI install together with that harness's credentials,
settings, caches, and other volume state. The next run or update recreates the volume and seeds the
CLI install from the current image. Removing `all` does this for every harness and also removes the
shared GPG volume.

## Security notes

Agent credentials, settings, session data, `.workcell/.env`, and GPG keys can contain secrets. Treat
Workcell Docker volumes, volume backups, shared context repos, and workspace-local `.workcell/` data
as sensitive according to what they contain.
