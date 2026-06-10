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

Do not modify `.workcell/ideas.md` or `.workcell/roadmap.md` without user approval. If you notice a possible improvement that does not fit the in-progress task, suggest adding it to `ideas.md` or `roadmap.md` and ask the user before editing either file. Exception: when completing a task that corresponds to the current `roadmap.md` item, remove or update that roadmap item as part of task completion.

When an item moves to the next stage, remove it from the previous stage so `ideas.md` and `roadmap.md` only describe work yet to be evaluated or implemented. They are not implemented-feature lists; completed work belongs in task directories. The first `roadmap.md` bullet should correspond to the task currently in progress when there is one, and should be removed when that task is completed.

## Project Workcell Layout

Project-specific workcell data lives under `.workcell/`:

- `.workcell/artifacts/` - temporary or heavy artifacts from agent work, such as screenshots, logs, traces, generated previews, and repeated visual captures. Agents may create optional subdirectories such as `screenshots/`, `logs/`, and `mockups/` when that helps organize related files. Put throwaway files here instead of the repo root or task directories.
- `.workcell/.env` - optional workspace-local environment variables loaded into sandboxed agent sessions. Treat it as secret-bearing and leave it ignored by Git.
- `.workcell/sessions/` - project-scoped agent session data, organized by harness:
  - `.workcell/sessions/pi/` - bind-mounted Pi project sessions when running the Pi harness.
  - `.workcell/sessions/opencode/` - exported OpenCode session backups.
  - `.workcell/sessions/codex/` - workspace-local Codex conversation files when running the Codex harness.
  - `.workcell/sessions/claude/` - bind-mounted Claude project sessions when running the Claude harness.
- `.workcell/ideas.md` - user-approved bullet list of possible future improvements yet to be properly evaluated.
- `.workcell/roadmap.md` - user-approved bullet list of next-direction items not yet fully converted into tasks.
- `.workcell/tasks/` - shared task notes for multi-step work and handoffs, organized by canonical status directories.
- `.workcell/flutter-config.json` - Flutter bridge launch settings and runtime connection details when Flutter integration is used.

Prefer timestamped artifact names in `.workcell/artifacts/` so files sort chronologically and avoid collisions, for example `screenshots/20260429-132400-home-page.png`.

Example `.workcell/` layout:

```text
.workcell/
├── .gitignore
├── .env
├── artifacts/
│   ├── screenshots/
│   ├── logs/
│   └── mockups/
├── sessions/
│   ├── claude/
│   ├── codex/
│   ├── opencode/
│   └── pi/
├── ideas.md
├── roadmap.md
├── tasks/
│   ├── accepted/
│   ├── current/
│   │   └── 20260608-165656-restructure-project-scoped-workcell-dir/
│   │       ├── task.md
│   │       ├── log.md
│   │       └── attachments/
│   ├── deferred/
│   ├── dropped/
│   └── finished/
└── flutter-config.json
```

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

Inside task files, use local time for logs and metadata. Determine the current local log time with:

```bash
date +'%Y-%m-%d %H:%M GMT%z' | sed -E 's/GMT([+-])0?([0-9]{1,2})00$/GMT\1\2/; s/GMT([+-])0?([0-9]{1,2})([0-9]{2})$/GMT\1\2:\3/'
```

This uses the configured local timezone and formats the timezone as a compact GMT offset, such as `GMT-3`, to keep entries short.

## Author Tag

Before creating or updating any `log.md`, determine the author tag in `<harness>/<model>` form. Examples include `pi/gpt-5.5`, `codex/gpt-5.5`, `claude/opus-4.8`, and `opencode/kimi-k2.6`; use the actual current harness and model rather than choosing from these examples.

- Use environment/configuration only when it clearly identifies both harness and model.
- In the Pi harness, when project Pi sessions are available, inspect the latest
  `.workcell/sessions/pi/*.jsonl` entry for the current model before asking the user. Prefer the
  latest assistant message's `provider` and `model`; otherwise use the latest `model_change` entry's
  `provider` and `modelId`.
- If either harness or model remains unknown, ask the user for the author tag before writing log
  entries.
- Do not write placeholder tags such as `unknown`, `pi/unknown`, or inferred model names unless the
  user explicitly instructs you to use that value.
- Reuse the confirmed author tag for subsequent log entries in the same session unless the harness or
  model changes.

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

Task directories may also contain an `attachments/` subdirectory for lightweight, task-specific files that help future readers understand, reproduce, or resume the task. Agents should expect task attachments to be committed to version control alongside `task.md` and `log.md`, so keep them intentional, small, and curated. Good candidates include focused test scripts, light mockups, supplementary notes, small fixtures, or other durable task context.

Use `.workcell/artifacts/` for files that should generally not be committed: heavy, noisy, generated, or temporary outputs such as screenshots, traces, large logs, build outputs, generated previews, repeated visual captures, and throwaway scripts. Use best judgment: if a file is durable task evidence or a reusable aid, put it in the task's `attachments/`; if it is transient work output, put it in `.workcell/artifacts/`.

## Maintenance Rules

Keep task files concise and operational. Record decisions, blockers, ownership boundaries, important commands, verification results, and links to attachments or artifacts. Put commit-worthy task support files under the task's `attachments/`; put large logs, screenshots, traces, and generated previews in `.workcell/artifacts/` instead of pasting them into the task file or committing them in the task directory.

Before the first `log.md` write in a session, confirm the author tag if it is not already known.

Keep `Plan` current with succinct notes about what was done and what remains. Add log entries to `log.md` in descending time order, using the confirmed author tag. Preserve previous log content. When a correction is needed, add an indented `CORRECTION` entry below the original entry or its previous corrections. Update status, plan checkboxes, and next steps in `task.md` as the task changes. A task directory's status parent must match the `Status` metadata in `task.md`; when changing status, move the task directory and update `task.md` in the same change. When pausing, leave concrete `Next Steps`. Only mark a task as `finished` after the user approves completion. When finishing an approved task, move the task to `finished`, set `Status` to `finished`, clear `Next Steps`, update `Updated`, summarize the outcome in `log.md`, and remove or update the corresponding current `roadmap.md` item if there is one.
