---
name: project-management
description: Use for project planning and non-trivial or multi-step work that benefits from continuity, including ideas, roadmap items, tasks, handoffs, research, risky debugging, or work likely to span sessions.
---

# Project Management

Use this skill for project planning files and `.workcell/tasks/` work that benefits from continuity: multi-step changes, handoffs, research, parallel-agent coordination, risky debugging, or anything likely to span sessions. Skip task creation for trivial one-step requests.

Task planning can flow through these stages:

```text
idea -> roadmap -> task
roadmap -> task
task
```

Using `.workcell/roadmap.md` is optional; users may choose to create task directories directly.

- `.workcell/ideas.md` contains succinct bullets for possible future improvements that still need evaluation.
- `.workcell/roadmap.md` contains succinct bullets for work that should be done next but has not yet been fully converted into task files.
- Bullets in either file may include nested sub-bullets when crucial context is needed, but keep them concise.
- `.workcell/tasks/<status>/<task>/` contains active or historical task state. The canonical statuses are:
  - `accepted` - accepted/scoped but not actively worked.
  - `current` - actively in progress.
  - `deferred` - blocked or waiting on a dependency/decision.
  - `dropped` - intentionally canceled or abandoned.
  - `finished` - completed.

Do not modify `.workcell/ideas.md` or `.workcell/roadmap.md` without user approval. If you notice a possible improvement that does not fit the in-progress task, suggest adding it to `ideas.md` or `roadmap.md` and ask the user before editing either file.

When an item moves to the next stage, remove it from the previous stage so `ideas.md` and `roadmap.md` only describe work yet to be evaluated or implemented. They are not implemented-feature lists; completed work belongs in task directories. The first `roadmap.md` bullet should correspond to the task currently in progress when there is one, and should be removed when that task is completed.

## Starting Work

Before starting non-trivial work or working on any `.workcell/tasks/` entry:

1. List `.workcell/tasks/` status directories, checking `current/` first, then `accepted/`, then other statuses only as needed.
2. Skim task directory names and the title line in each `task.md` only. Do not read full task files yet.
3. Ask the user how to track the work: continue a previous task (including likely matches by title when any exist), create a new task, or skip task creation.
4. Read only the task directory the user chooses: `task.md` for task state and `log.md` for history.
5. Create a new task directory only when the user asks for a new one.

Task directory names use UTC timestamp prefixes and live under their matching status directory:

```text
.workcell/tasks/<status>/YYYYMMDD-HHMMSS-brief-descriptive-slug/
```

Inside task files, use local time for logs and metadata. Check the `TZ` environment variable to determine the configured local timezone, then write the timezone as a compact GMT offset, such as `GMT-3`, to keep entries short.

## Task Directory Structure

Each task directory should include `task.md`:

```markdown
# <Short Title>

- **Status:** accepted | current | deferred | dropped | finished
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

Keep `Plan` current with succinct notes about what was done and what remains. Add log entries to `log.md` in descending time order, and include the authoring harness/model, such as `codex/gpt-5.5`, when known. If the harness/model is unknown, ask the user; do not infer it from previous log entries. Preserve previous log content. When a correction is needed, add an indented `CORRECTION` entry below the original entry or its previous corrections. Update status, plan checkboxes, and next steps in `task.md` as the task changes. A task directory's status parent must match the `Status` metadata in `task.md`; when changing status, move the task directory and update `task.md` in the same change. When pausing, leave concrete `Next Steps`. When finished, move the task to `finished`, set `Status` to `finished`, clear `Next Steps`, update `Updated`, and summarize the outcome in `log.md`.
