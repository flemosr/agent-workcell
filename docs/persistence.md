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
| Pi | `~/.pi/agent/` for Pi settings, auth, packages/extensions, context, skills, and the managed Pi launcher at `~/.pi/agent/bin/pi` with releases under `~/.pi/agent/install/`. Project Pi sessions live under `.workcell/sessions/pi/`. |
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
| Pi | `~/.pi/agent/install/` and `~/.pi/agent/bin/pi` | `pi update --self` |
| OpenCode | `~/.opencode/` | `opencode upgrade --method curl` |
| Codex | `~/.codex/packages/standalone/` | `codex update` |
| Claude | `~/.local/share/claude/` | `claude update` |

Workcell's bundled Pi extensions are different from the Pi CLI install. The Pi image owns:

- `/opt/workcell/pi-extensions/compact-session.ts` — the default self-compaction entrypoint;
- `/opt/workcell/pi-extensions/compact-session-runtime.ts` — its sibling runtime helper;
- `/opt/workcell/pi-extensions/reasoning-effort.ts` — model information and effort-selection tools;
- `/opt/workcell/pi-extensions/context-usage.ts` — the read-only active-context usage getter; and
- `/opt/workcell/pi-extensions/terminal-notify.ts` — the optional cmux notification adapter.

The launcher explicitly loads the compaction, reasoning-effort, and context-usage entrypoints on
Pi runs, and the notification adapter only when enabled. These files are not copied into
`~/.pi/agent/extensions/` and do not modify Pi settings.
Pulling changes to them requires `workcell pi build` and a new container. Rebuilding does not replace
the volume-backed Pi executable, so run `workcell pi update` separately if the persisted Pi version
lacks the required extension APIs. Volume backups include the persisted Pi install and user
extensions, but not these image-owned files. See [Pi self-compaction](pi-self-compaction.md),
[Pi reasoning effort](pi-reasoning-effort.md), and [Pi context usage](pi-context-usage.md) for tool
behavior, tested versions, disabling, and acceptance checks.

Harness startup seeds image-provided installs into the selected volume. After initialization, the
persisted install is authoritative: container restarts and image rebuilds restore the launcher from
the volume and do not replace a valid install with the image template. For Pi, seeding occurs only
when `agent/install/` is absent; an invalid existing install is an error, not a reason to reseed.
Use `workcell <agent> update` to ask the native updater for the newest policy-allowed release.
Update commands do not accept a version argument.

Claude Code can retain multiple installed versions, including a newer binary after a release-channel
downgrade. Workcell therefore records the launcher selected by a successful `claude update` in
`~/.local/share/claude/.workcell-current-version` and restores that version on restart instead of
blindly selecting the highest installed version.

When upgrading an existing Workcell checkout from the older image-owned harness layout, rebuild each
existing harness image once with `workcell <agent> build` to acquire the persistence wiring. Existing
volume state is preserved, and missing persistent installs are seeded non-destructively when the
rebuilt image first starts. Pi's older npm `self/` tree is neither used nor converted by managed
startup; see the install-only reset below before discarding it.

## Managed Pi lifecycle

Pi's image seed is an agent-owned managed directory at `/opt/pi-template`, also available through
`/opt/pi`. The official installer creates it at build time using the base image's Node/npm and
upstream's published release lock with `npm ci --ignore-scripts`. An uncached installer layer selects
the latest upstream release; Docker's build cache can retain an older seed. Published locks pin
dependency versions, but are not an independent authentication check of upstream artifacts.

The template/config/cache/offline/telemetry settings are scoped to build commands, not permanent
runtime configuration. Build and runtime use `/home/agent` as HOME, so the installer marker's
`/home/agent/.local/bin/pi` entrypoint remains correct without rewriting it. Pi does not provision a
second Node installation; Node/npm remain managed by Workcell's base-image/runtime setup.

Inside the Pi volume, install-owned files are separate from user configuration and resources:

```text
/home/agent/persist/.pi/agent/
├── bin/pi                         # upstream managed launcher
└── install/
    ├── managed-install.json       # managed ownership/layout marker
    ├── current-version            # selected release, not the highest retained version
    ├── releases/<version>/        # release locks and node_modules
    └── staging/                   # native updater staging area

/home/agent/.local/bin/pi -> /home/agent/persist/.pi/agent/bin/pi
```

- **First startup:** if `install/` is absent, copy only the image's install tree into a temporary
  sibling on the volume, validate/chown it, and publish it by a same-filesystem rename. Restore the
  managed launcher separately. Initialization does not invoke the installer, npm, curl, or a
  self-update; it needs no installation network access. A competing seed fails clearly for retry
  rather than overwriting an install published by another initializer.
- **Restarts and rebuilds:** validate the existing marker, selector, and selected executable locally.
  Preserve that release even if the image seed is older or newer, and never choose the highest
  retained version. Missing/nonexecutable `bin/pi` is restored atomically from the image without
  changing releases or selection; an existing executable launcher is retained. Corrupt install
  metadata, missing/nonexecutable selected binaries, and rejected symlink/escaping layouts fail
  startup rather than falling back to the image or legacy `self/` tree.
- **Native updates:** `workcell pi update` delegates to `pi update --self` in a helper container using
  the same volume. Pi owns update locking, locked dependency installation, staging, and atomic
  selector switching. The launcher derives `PI_MANAGED_INSTALL_ROOT` from its runtime location;
  do not bypass it with a version-specific executable. Managed Pi rejects `--force`; it is not a
  repair or release-transition test. An already-current result is valid for a fresh latest seed.

The install location is fixed even when `PI_CODING_AGENT_DIR` overrides Pi's configuration directory.
Install seeding does not replace auth, settings, sessions, context, skills, user packages/extensions,
or the unused legacy `self/` tree. Bundled Workcell extensions remain image-owned as described above.

### Pi install-only reset and recovery

**Do not remove executable files backing an active Pi session.** First validate the rebuilt image
against a disposable Pi volume on a Docker-capable host, including offline startup, root-to-agent
ownership/writability, restart selection, native managed update detection, and bundled-extension
loading. See [Pi acceptance checks](pi-self-compaction.md#host-managed-install-check). Then exit all
Pi sessions and stop every Pi container using the volume, including other workspaces and update
helpers. Inspect paths before deletion; do not follow unexpected directory symlinks.

For the initial cleanup of an older private npm install:

1. Build the managed image with `workcell pi build` and complete the disposable-volume acceptance
   above before resetting the personal install. The changed installer layer is rebuilt normally;
   `--no-cache` is not required for this layout change.
2. With all Pi users of the volume stopped, optionally make a backup with
   `workcell volume backup --file agent-workcell-backup.tgz`. It contains credentials and GPG keys;
   protect it accordingly.
3. Run `workcell volume shell pi`. This opens a helper shell with the volume at `/data`, without
   invoking Pi startup. Remove only the unused executable prefix:

   ```sh
   rm -rf /data/.pi/agent/self
   ```

   No npm uninstall is required. Do not delete `/data/.pi/agent`, `.pi`, or the whole volume.
4. Exit the helper shell. `workcell pi run -- --version` starts the rebuilt image and seeds the
   managed install if absent. Check `workcell pi update`, then run the version check again in a
   subsequent container to confirm persistence.

For later managed corruption, first use the same acceptance/stop/backup precautions. A damaged
executable launcher alone can be replaced by removing only `/data/.pi/agent/bin/pi`; startup restores
it from the image. This assumes `agent/` and `agent/bin/` are real directories. If `agent/bin` is an
unexpected symlink, remove only that link instead of deleting a file through it; never remove its
target. To discard a damaged managed install with real parent directories, run in the volume helper:

```sh
rm -rf /data/.pi/agent/install
rm -f /data/.pi/agent/bin/pi
```

The next startup seeds the image release, so this reset discards the selected version and all retained
managed releases, but preserves auth, settings, sessions, context, skills, and user packages. It also
avoids the inspected Pi 1.0.3 installer's same-version reinstall behavior, which can reuse an existing
release rather than repair it. Do not use `workcell volume rm pi` as an executable repair.

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

Pi native updates retain earlier managed release trees. Volume size and backups can therefore grow
with updates; rebuilding the image does not prune those releases. An install-only reset discards
that release history and returns to the image seed, not necessarily the latest upstream version.

Removing a harness volume removes its persisted CLI install together with that harness's credentials,
settings, caches, and other volume state. The next run or update recreates the volume and seeds the
CLI install from the current image. Removing `all` does this for every harness and also removes the
shared GPG volume.

## Security notes

Agent credentials, settings, session data, `.workcell/.env`, and GPG keys can contain secrets. Treat
Workcell Docker volumes, volume backups, shared context repos, and workspace-local `.workcell/` data
as sensitive according to what they contain.
