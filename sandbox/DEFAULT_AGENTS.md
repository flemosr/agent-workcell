# Agent Workcell Context

You are running inside an Agent Workcell Docker container: an opinionated, isolated environment for
running TUI coding agents with selective persistence, optional Chrome/Flutter integrations, and
project-scoped workflow state. Treat this file as the general sandbox context.

For user questions about the Agent Workcell sandbox environment, first check the user-facing docs in
`/opt/workcell-docs/`.

## Global Context And Skills

Load focused workflow skills when they are relevant to the task.

- You MUST load the `project-management` skill before working on `.workcell/ideas.md`,
  `.workcell/roadmap.md`, any `.workcell/tasks/` entry, or when the user describes a new
  non-trivial task.
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
- For `browser sandbox ...`, `localhost` means inside the container; for `browser host ...`, `localhost` means the host and container dev servers need exposed ports.
- Your current project directory is bind-mounted from the host. File changes in the workspace persist automatically.
- The container runs as a non-root `agent` user for normal agent commands.
- Filesystem access is scoped to the mounted workspace and persisted user data.
- Interactive project scaffolding prompts usually do not work. Prefer non-interactive CLI flags.

## Persistence

The workspace directory is bind-mounted from the host. Harness state, credentials, settings,
conversation/session data, language package caches, and installed user tools persist for the
selected agent harness. Do not assume other harnesses' persisted state or binaries are present.

Treat `.workcell/.env` as secret-bearing if present. Flutter bridge runtime settings may appear in
`.workcell/flutter-config.json` when Flutter integration is used.

## Exposed Ports

Check exposed container ports with:

```bash
echo "$EXPOSED_PORTS"
```

If `$EXPOSED_PORTS` is set, dev servers on those ports are reachable from the host at `localhost:<port>`. If a needed port is not exposed, tell the user they can restart the sandbox with `--port <port>`.

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
| Browser | `browser` CLI with `sandbox` headless Chromium and explicit `host` Chrome modes; use the `chrome-integration` skill before browser/web work |
| Flutter | `flutter` and `dart` for tests, analysis, formatting, and pub; `flutterctl` for the host bridge (launch, hot-reload, screenshots); use the `flutter-integration` skill before native Flutter work |
| Protobuf | `protoc`, `buf`, `protoc-gen-dart`, `protoc-gen-prost`, `grpcurl` |
| Database | `psql`; connect to host databases through `host.docker.internal` |
| Utilities | `git`, `curl`, `wget`, `jq`, `yq`, `ripgrep`, `fd` |
