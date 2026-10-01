# Pi Self-Compaction

Workcell bundles `compact_session`, a model-callable tool that compacts the active Pi session and
then automatically continues **that same session** with a prompt supplied by the agent. It uses
Pi's native compaction rather than a replacement summarizer.

The agent invokes it during the interactive TUI without a confirmation dialog, manual `/compact`,
or manual resume step. It is not a Workcell CLI command or a new slash command. Operational guidance
is included in the tool description and prompt guidelines; agents do not need to read this page to
use it.

## Enable or disable

The tool is enabled by default on interactive Workcell Pi launches, independently of notifications:

```bash
workcell pi run
```

To disable it for a launch, forward Pi's existing tool-exclusion option after Workcell's `--`:

```bash
workcell pi run -- --exclude-tools compact_session
```

This is a Pi argument, not a new Workcell option or configuration setting. Native `--tools` allowlists
and `--no-tools` also remain authoritative; the extension does not re-enable an excluded tool.
`--no-builtin-tools` disables default built-ins, not this extension tool.

Workcell explicitly loads `/opt/workcell/pi-extensions/compact-session.ts`, so Pi's `--no-extensions`
disables discovery but **does not disable this bundled extension**. Use tool exclusion instead.

Version 1 supports **TUI mode only**. The module can load for print (`-p`/`--print`), JSON, or RPC
launches, but the tool is disabled there and rejects execution outside TUI mode. Other Workcell
harnesses are unaffected.

## Tool parameters

Example model tool call:

```typescript
compact_session({
  resumePrompt: "Continue the approved implementation slice; stop at its review/commit gate.",
  customInstructions: "Preserve the approved plan, completed work, and pending approval gates."
});
```

| Parameter | Required | Meaning |
|-----------|----------|---------|
| `resumePrompt` | Yes | Non-empty agent-authored continuation. Whitespace-only strings are rejected; valid strings are delivered exactly, including leading/trailing whitespace and newlines. |
| `customInstructions` | No | Native summary focus, separate from the continuation. Non-blank strings are forwarded unchanged; blank strings are omitted. |

Call it **alone in a tool batch**, not alongside another tool or another compaction. It is model-only
and cannot be invoked through codemode or nested tool execution. Only one request may be pending.

After a successful resume, another self-compaction requires a later recorded user message or a
successful non-compaction tool result on the active branch. Merely typing, input consumed by another
extension, or failed work does not unlock repeated compaction. Reloading does not erase this guard.

Automatic continuation does not authorize new work. The agent must preserve existing review,
approval, and commit boundaries in its plan and continuation prompt. Persist essential decisions
and constraints before compacting rather than relying on summary instructions to retain them.

## What happens

1. The tool validates the call and returns **“Compaction queued.”** This acknowledges an accepted
   request, not a completed summary.
2. After the matching tool result is finalized in history, the extension schedules native
   compaction. Pi owns the summary, retained-context settings, compaction hooks, model/auth routing,
   history persistence, and usage accounting.
3. Only after successful compaction, while the originating session/branch is still valid and the
   request has not been canceled, the extension dispatches one visible continuation message with
   the exact `resumePrompt` and starts another model turn. It does not create a session or fork, and
   the message is extension-owned rather than presented as user-authored input.

Compaction is **lossy**: the model sees a summary plus retained recent context, not the entire old
conversation. Original session entries remain in Pi's history. `customInstructions` is a focus
hint, not guaranteed preservation or a change to retention budgets. On the tested Pi version,
split-turn compaction can generate a separate prefix summary; the instructions apply to the history
summary, not that separate prefix request.

Compaction and resumed model work can incur normal provider usage. Disabling Pi's automatic
threshold compaction does not disable this explicitly requested native compaction.

## Queued input and interruption

Queued text **does not cancel or replace** the captured continuation. After successful compaction,
the extension dispatches `resumePrompt` before queued text is consumed by a model request. Pi then
handles the text through its ordinary steering/follow-up queues without extension-owned queue
rewriting. Already-queued messages can be recorded during native abort before the resume message;
the ordering contract concerns model consumption, not history append order. Slow third-party input
handlers can produce a later separate user run.

Escape, or the active Pi interrupt binding, is different from queued text:

- While a transition is pending, interruption cancels the request and prevents automatic resume.
- After continuation starts, normal Pi interruption aborts the resumed work; the extension does not
  restart it.
- A summary already persisted before interruption is not rolled back. Native queued-text restoration
  remains Pi-owned.

The extension observes interrupt keys without consuming them. Earlier terminal-input extensions
that consume or remap a key can hide it from both this observer and native Pi. Arbitrary input
consumers/custom editors are not guaranteed to preserve cancellation behavior.

## Failure and readiness

Invalid/mixed calls, native small-session or already-compacted errors, hook cancellation, provider
failure, and explicit interruption do not trigger continuation. The extension does not retry the
compaction request. Session/branch navigation, reload, or shutdown can invalidate pending
continuation; saved tool acknowledgements are not replayed as jobs. Exactly-once dispatch is a
live-runtime guarantee, not crash-safe delivery after restarting Pi.

Self-compaction works without cmux or notifications. When the optional
[cmux notification adapter](cli.md#pi-completion-notifications-in-cmux) is enabled, it suppresses the
intermediate native settlement between compaction and resume. Readiness follows resumed/queued
work settling; failure or cancellation may announce readiness when idle with no pending work.
“Ready for input” does not mean the task succeeded. The existing notification opt-in and cmux
identity requirements are unchanged.

## Installation and compatibility

The entrypoint and sibling helper are image-owned files, not user-installed extensions. After
updating this checkout, rebuild the Pi image; updating the persisted Pi executable is a separate
operation. See [Persistence](persistence.md#image-baked-tools-and-volume-backed-harness-installs).

This integration is tested with **Pi 0.99.2**. Older persisted installs may lack required APIs;
rebuilding an image does not replace them. Use `workcell pi update` when needed, then run the
acceptance checks for the installed version. Compatibility with other versions is not assumed.

## Acceptance checks

Automated tests use isolated settings/credentials and fake provider responses, with network
forbidden. They cover native compaction/history/accounting, exact continuation, autonomous repeated
slices, queues/interrupts, selection/mode guards, lifecycle cleanup, notification behavior, and
loading relocated copies of the image's extension files.

From the repository root, with Python, Node supporting type stripping, and Pi installed:

```bash
python -m unittest discover -s tests -p 'test_pi_compaction*.py'
python -m unittest discover -s tests -p 'test_pi_notifications.py'
python -m unittest discover -s tests -p 'test_run_sandbox_launcher.py'
python -m unittest discover -s tests -p 'test_sandbox_image_split.py'
python -m unittest discover -s tests
```

Set `PI_TEST_PACKAGE_ROOT=/path/to/installed/pi-package` if Pi is not discoverable through `PATH`.
A skipped SDK suite does not establish acceptance. Copied-layout and simulated-terminal tests are
**not a real Docker build or physical TUI acceptance**; that path still requires a host check.

### Host image/TUI check

Run this on a host with Docker and a physical terminal. Use a disposable workspace and fresh
ephemeral session, not a production conversation. Live model checks can incur provider charges;
run them only with permission to use the configured provider.

1. Rebuild with `workcell pi build` and check the installed version with
   `workcell pi run -- --version`; update an older executable separately if needed. Start
   `workcell pi run -- --no-session` and record the session ID using `/session`.
2. Build enough non-sensitive, read-only conversation history to compact under the current retention
   settings. Authorize the agent to call `compact_session` alone, with a specific continuation that
   performs one harmless read and stops. Confirm the queued acknowledgement, native compaction,
   exact visible continuation, unchanged session ID, and autonomous read without a dialog or manual
   resume. A native small-session rejection is an error-path check, not proof of successful resume.
3. Repeat with steering/follow-up text queued during compaction. Confirm the supplied continuation
   is dispatched and queued input reaches the model afterward, once, in its native mode.
4. Repeat with the active interrupt key during compaction and during resumed work. Confirm no
   unwanted restart; verify queued-text restoration and that an already-saved summary stays saved.
5. Relaunch with `workcell pi run -- --no-session --exclude-tools compact_session` and confirm the
   tool is unavailable. Test normal operation without notification opt-in; if using cmux, also test
   with the existing opt-in and confirm no readiness notification in the compaction/resume gap.

Record the Pi version, terminal/notification configuration, and pass/fail results before declaring
host acceptance. Ephemeral sessions cannot be resumed after exit; no pending continuation is
replayed on restart.
