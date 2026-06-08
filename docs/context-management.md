# Context Management

Agent Workcell manages each harness's global context and global skills through Workcell-owned source paths inside the harness Docker volume. Optionally, a user-managed shared context repo can override those per-harness sources across workspaces and harnesses.

## Context layers

Global context is resolved in this order:

1. **Shared context repo**: `/opt/workcell-context/GLOBAL_AGENTS.md`, when `WORKCELL_CONTEXT_REPO` is configured and the file exists.
2. **Persisted harness context source**: `workcell-context.md` inside the selected harness Docker volume.
3. **Image default**: `/opt/agent-context.md`, baked from `sandbox/DEFAULT_AGENTS.md`, used only to seed or restore a persisted/repo source.

Harness-native paths are symlinks to the in-effect source:

| Harness | Native context | Persisted context source |
|---------|----------------|--------------------------|
| Pi | `~/.pi/agent/AGENTS.md` | `~/.pi/agent/workcell-context.md` |
| OpenCode | `~/.config/opencode/AGENTS.md` | `~/.config/opencode/workcell-context.md` |
| Codex | `~/.codex/AGENTS.md` | `~/.codex/workcell-context.md` |
| Claude | `~/.claude/CLAUDE.md` | `~/.claude/workcell-context.md` |

## Default context seeding

On first use without an effective repo `GLOBAL_AGENTS.md`, Workcell creates the selected harness's persisted `workcell-context.md` by copying the baked image default `/opt/agent-context.md`.

After that first seed, the persisted file is user data. Rebuilding images or updating Workcell does not overwrite it. To intentionally replace the in-effect context with the current image default, run:

```bash
workcell <pi|opencode|codex|claude> context restore
```

`context restore` asks for confirmation before overwriting the in-effect source.

## Context change persistence

`context open` opens the real in-effect source and prints the exact path:

```bash
workcell pi context open
```

Where edits persist depends on which source is in effect:

- **No shared context repo, or repo has no `GLOBAL_AGENTS.md`:** edits persist in that harness's Docker volume at its `workcell-context.md` source.
- **Shared context repo with `GLOBAL_AGENTS.md`:** edits persist in the host context repo file mounted at `/opt/workcell-context/GLOBAL_AGENTS.md` and affect all workspaces/harnesses using that repo.

The image default is not an active editable source during normal use. It is only copied into a persisted/repo source during initial seeding or explicit restore.

## Optional shared context repo mounting

Configure a shared context repo by setting `WORKCELL_CONTEXT_REPO` in repository-root `config.sh` to an absolute host path:

```bash
WORKCELL_CONTEXT_REPO="/Users/you/agent-context"
```

This setting is intentionally read only from root `config.sh`; shell environment variables and `.workcell/.env` are not supported for `WORKCELL_CONTEXT_REPO`.

When configured, the repo is mounted writable inside sandboxes at:

```text
/opt/workcell-context
```

Supported layout is intentionally limited to:

```text
agent-context/
├── GLOBAL_AGENTS.md
└── skills/
    └── <skill-name>/SKILL.md
```

`GLOBAL_AGENTS.md` is optional. If it is absent, Workcell falls back to the harness persisted `workcell-context.md`, seeding that file from the image default if needed. If it is present, it becomes the in-effect global context for every harness/workspace using the repo.

The context repo is user-managed and should usually be tracked in Git. Because the mount is writable, `context open` and `context restore` can change `GLOBAL_AGENTS.md` in the host repo when it is the in-effect source.

## Skills relationship

Skills use the same precedence idea, but as a merged directory view:

1. Repo skills from `/opt/workcell-context/skills/<skill-name>/SKILL.md`, when present.
2. Persisted harness-volume skills from `workcell-skills`.
3. Baked image default skills, copied into `workcell-skills` on first use and used as restore sources.

Repo skills shadow persisted skills with the same name; non-conflicting persisted skills remain visible. Harness-native `skills/` paths point to ephemeral merged views under `/tmp/workcell-merged-skills/<harness>`, so do not edit the merged view directly.

Use:

```bash
workcell <harness> skill list
workcell <harness> skill open <skill-name>
workcell <harness> skill restore <skill-name>
```

`skill open` opens the real in-effect source. If a new skill is created while a shared context repo is mounted, it is created in the repo; otherwise it is created in the harness's persisted `workcell-skills` source.
