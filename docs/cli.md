# CLI reference

## Build

```bash
# Build all agent images
workcell build

# Or build one agent image plus the shared base
workcell pi build
```

`workcell build` runs `docker compose build` from the workcell repository root, so it works even
when you invoke `workcell` from another directory, and builds all four agent images plus the
shared base. To build a single agent, use the harness subcommand form:
`workcell <agent> build` where agent is `pi`, `opencode`, `codex`, or `claude`.

## Update harnesses

```bash
workcell pi update
workcell opencode update
workcell codex update
workcell claude update
```

Each command delegates release selection and installation to the harness's native updater:

| Workcell command | Native command |
|------------------|----------------|
| `workcell pi update` | `pi update --self` |
| `workcell opencode update` | `opencode upgrade --method curl` |
| `workcell codex update` | `codex update` |
| `workcell claude update` | `claude update` |

Update commands do not accept a version argument. "Latest" means the newest release allowed by the
native updater's policy rather than an unconditional latest release. In particular,
`workcell claude update` respects Claude Code's configured update channel, minimum version, and
managed version bounds.

The update runs in a short-lived container with the selected harness volume and an empty temporary
GPG home; it does not expose the shared GPG volume, current workspace, or project `.workcell/` data.
If the selected image is missing, Workcell builds the shared base and that harness image first. An
existing image is used without rebuilding it on every update.

Harness installs are stored in their per-harness volumes, so the updated executable remains selected
across container restarts and image rebuilds. After upgrading from a Workcell version that predates
volume-backed harness installs, rebuild each existing harness image once with
`workcell <agent> build`; existing harness-volume state is migrated non-destructively when the new
image starts. See [Persistence](persistence.md) for install paths, precedence, and backup behavior.

## Run agents

Navigate to any project directory and run:

```bash
# Normal mode
workcell pi run  # Pi does not use permission prompts by default
workcell opencode run
workcell codex run
workcell claude run

# YOLO mode (no permission prompts)
workcell opencode run --yolo
workcell codex run --yolo
workcell claude run --yolo

# Firewalled mode (restricted network access)
workcell codex run --firewalled

# With a prompt
workcell claude run --yolo -- -p "fix the tests"

# Pass agent-specific arguments after --
workcell pi run -- -p "summarize the repo"
workcell opencode run -- run "summarize the repo"
workcell codex run -- "fix the tests"
workcell claude run -- --resume
```

The agent is the first positional argument and is required: `pi`, `opencode`, `codex`, or
`claude`. Each agent uses its own sandbox image and persistent Docker volume, plus a shared GPG
volume. If the selected image is missing, `workcell <agent> run` builds that agent image and the
shared base automatically.

`--with-chrome` and `--with-flutter` are mutually exclusive. Sandbox-headless browser commands
(`browser sandbox ...`) are available inside the image and do not require `--with-chrome`.
`--with-chrome` enables explicit host Chrome workflows (`browser host ...`). `--port` exposes
container dev servers to the host in all modes; it is required for host Chrome to reach container
servers, but not for sandbox-headless browsing. In Flutter mode, use `--bridge-port` to select the
host Flutter bridge port. If the Flutter project is in a workspace subdirectory, pass
`--flutter-project-dir ./gui`.

`--yolo` maps to each agent's native bypass where one exists:

- **pi**: ignored because Pi does not ask for permissions by default; the container is the
  permission boundary
- **opencode**: `{"permission":"allow"}` injected through `OPENCODE_CONFIG_CONTENT`
- **codex**: `--dangerously-bypass-approvals-and-sandbox`
- **claude**: `--dangerously-skip-permissions`

Running `workcell` or `workcell <agent>` without a subcommand exits with a usage error instead of
choosing an agent implicitly.

```bash
workcell codex run --yolo
```

See [Integrations](#integrations) for Chrome, Flutter, and port examples.

## Integrations

```bash
# Sandbox-headless browsing is available by default inside agents
workcell pi run

# Host Chrome enabled for user-visible web development/profile workflows
workcell pi run --with-chrome
workcell codex run --yolo --with-chrome --port 3000

# Expose container dev-server ports to the host
workcell opencode run --port 3000
workcell codex run --port 3000 --port 5173

# Start Chrome independently on the host
workcell start-chrome
workcell start-chrome --restart
workcell start-chrome --port 9333 --profile "Profile 1"

# Flutter native/device bridge
workcell pi run --with-flutter
workcell codex run --with-flutter --bridge-port 8765
workcell codex run --with-flutter --flutter-project-dir ./gui
workcell codex run --with-flutter --bridge-port 8766 --port 3000

# Start the Flutter bridge independently on the host
workcell start-flutter-bridge
workcell start-flutter-bridge --port 8766 --project ~/my-flutter-app
workcell start-flutter-bridge --flutter-project-dir ./gui
```

See [Chrome integration](chrome-integration.md) for `browser sandbox ...` and `browser host ...`
usage, and [Flutter integration](flutter-integration.md) for Flutter setup details.

## Pi completion notifications in cmux

Workcell can notify cmux when an interactive Pi run has fully settled and is ready for input. This
uses cmux's OSC 777 terminal notification protocol over the existing Docker TTY; it does not mount a
cmux socket, forward `CMUX_*` variables, or run a host bridge.

Two conditions must be true at launch:

1. The effective host-side setting is exactly `WORKCELL_PI_NOTIFICATIONS=enabled`.
2. cmux supplied a nonempty `CMUX_SURFACE_ID`, or the legacy `CMUX_PANEL_ID`, to the shell launching
   Workcell.

`config.template.sh` enables the feature, so new configurations copied from it opt in. Existing
`config.sh` files are not changed automatically; add the setting manually:

```bash
# config.sh
WORKCELL_PI_NOTIFICATIONS=enabled
```

Without an assignment in `config.sh`, the host environment can opt in for one launch:

```bash
WORKCELL_PI_NOTIFICATIONS=enabled workcell pi run
```

Repository-root `config.sh` takes precedence over an inherited host value. Unset, empty, and every
value other than the exact lowercase word `enabled` disable the feature. To disable it when the
template assignment is present, remove that assignment or change its value, for example:

```bash
WORKCELL_PI_NOTIFICATIONS=disabled
```

`.workcell/.env` cannot enable this host launch policy. Workcell also filters
`WORKCELL_PI_NOTIFICATIONS` and `CMUX_*` entries from that file rather than forwarding them into the
container.

When enabled, Workcell explicitly adds its image-owned extension with `--extension`; Pi's
`--no-extensions` option disables discovery but does not disable this explicit extension. The
extension emits the fixed `Pi` / `Ready for input` notification only for TUI mode with a terminal and
an idle agent. It listens to Pi's `agent_settled` event, so the notification means "ready for input,"
not "the task succeeded." Print (`-p`), JSON, and RPC modes emit no notification.

cmux controls whether a focused pane shows a banner and how unread or pane-attention indicators are
displayed. If no notification appears:

- confirm the launch shell has `CMUX_SURFACE_ID` or `CMUX_PANEL_ID` and that the effective setting is
  exactly `enabled`;
- rebuild the Pi image with `workcell pi build` so it contains the Workcell extension;
- update older persisted Pi installs with `workcell pi update`; this integration is tested with Pi
  0.85.1 and requires `agent_settled` plus extension context modes;
- check cmux notification preferences, preferably while the Pi pane is unfocused; and
- disable either Workcell's setting or any user-installed notification extension if notifications
  appear twice.

To check cmux's OSC handling independently, run this in a host cmux shell and switch to another pane
during the delay:

```bash
sleep 3; printf '\033]777;notify;Pi;Ready for input\a'
```

This host check does not cover Docker's attached TTY; complete that path with a real interactive Pi
prompt. Pi's `!` user-shell subprocesses capture output and do not have a writable direct path to the
container TTY, so they are not a valid transport probe.

## Settings, context, and skills

```bash
workcell pi settings
workcell opencode settings
workcell codex settings
workcell claude settings

workcell pi context open
workcell opencode context open
workcell codex context open
workcell claude context open
workcell pi context restore

workcell pi skill list
workcell opencode skill list
workcell codex skill list
workcell claude skill list
workcell pi skill open chrome-integration
workcell pi skill restore chrome-integration
```

The `settings` commands open an agent's config file in `vi` inside the workcell Docker volume.
The `context` commands manage the in-effect global context source, which is either a persisted
harness-volume `workcell-context.md` file seeded from the image default or, when configured, a
shared repo `GLOBAL_AGENTS.md`. The `skill` commands manage global skills from persisted
harness-volume sources plus optional shared repo skills. See [Context management](context-management.md)
for default seeding, persistence, shared context repo mounting, and skill precedence details.

## GPG keys

```bash
workcell gpg new
workcell gpg export --file my-key-backup.asc
workcell gpg import --file my-key-backup.asc
workcell gpg revoke --file revoke.asc
workcell gpg erase
```

See [GPG setup](gpg-setup.md) for key setup, backup, and rotation guidance.

## OpenCode sessions

```bash
workcell opencode sessions export
workcell opencode sessions import
```

These commands export and import OpenCode sessions between the Docker volume and
`.workcell/sessions/opencode/`.

## Project workcell migration

```bash
workcell migrate
```

This temporary command migrates legacy project session directories from
`.workcell/<harness>-sessions/` to `.workcell/sessions/<harness>/`, converts timestamped
`.workcell/tasks/*.md` task files into task directories with `task.md` plus `log.md`, and moves
flat task directories under status directories. Run it once in existing projects created with the
older layout.

## Volume management

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

Volume commands affect the Docker-volume user data described in [Persistence](persistence.md).
