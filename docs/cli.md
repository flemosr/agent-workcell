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

`--with-chrome` and `--with-flutter` are mutually exclusive. `--port` exposes container dev
servers to the host in all modes. In Flutter mode, use `--bridge-port` to select the host Flutter
bridge port. If the Flutter project is in a workspace subdirectory, pass
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
# Chrome enabled for web development
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

See [Chrome integration](chrome-integration.md) and [Flutter integration](flutter-integration.md)
for setup details.

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

Volume commands affect the persisted user data described in the README.
