---
name: task-management
description: Use for non-trivial or multi-step work that benefits from continuity, including planning, handoffs, research, risky debugging, or tasks likely to span sessions.
---

# Task Management

Use `.workcell/tasks/` for work that benefits from continuity: multi-step changes, handoffs, research, parallel-agent coordination, risky debugging, or anything likely to span sessions. Skip task creation for trivial one-step requests.

## Starting Work

Before starting non-trivial work:

1. List `.workcell/tasks/`.
2. Skim task directory names and the title line in each `task.md` only. Do not read full task files yet.
3. Ask the user how to track the work: continue a previous task (including likely matches by title when any exist), create a new task, or skip task creation.
4. Read only the task directory the user chooses: `task.md` for task state and `log.md` for history.
5. Create a new task directory only when the user asks for a new one.

Task directory names use UTC timestamp prefixes:

```text
YYYYMMDD-HHMMSS-brief-descriptive-slug/
```

Inside task files, use local time for logs and metadata. Check the `TZ` environment variable to determine the configured local timezone, then write the timezone as a compact GMT offset, such as `GMT-3`, to keep entries short.

## Task Directory Structure

Each task directory should include `task.md`:

```markdown
# <Short Title>

- **Status:** pending | in_progress | blocked | completed | cancelled
- **Created:** <YYYY-MM-DD HH:MM GMT-offset>
- **Updated:** <YYYY-MM-DD HH:MM GMT-offset>

## Objective
## Context
## Plan
## Next Steps
## Dependencies
## Notes
```

Each task directory should also include `log.md`:

```markdown
# <Short Title> Log

- `<YYYY-MM-DD HH:MM GMT-offset>` | `<author>` | <entry>
  - **CORRECTION** | `<YYYY-MM-DD HH:MM GMT-offset>` | `<author>` | <correction>
```

## Maintenance Rules

Keep task files concise and operational. Record decisions, blockers, ownership boundaries, important commands, verification results, and links to artifacts. Put large logs, screenshots, traces, and generated previews in `.workcell/artifacts/` instead of pasting them into the task file.

Keep `Plan` current with succinct notes about what was done and what remains. Add log entries to `log.md` in descending time order, and include the authoring harness/model, such as `codex/gpt-5.5`, when known. If the harness/model is unknown, ask the user; do not infer it from previous log entries. Preserve previous log content. When a correction is needed, add an indented `CORRECTION` entry below the original entry or its previous corrections. Update status, plan checkboxes, and next steps in `task.md` as the task changes. When pausing, leave concrete `Next Steps`. When finished, set `Status` to `completed`, clear `Next Steps`, update `Updated`, and summarize the outcome in `log.md`.
