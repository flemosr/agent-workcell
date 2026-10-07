# Pi Context Usage

Workcell bundles `get_context_usage`, a read-only Pi tool that returns a small snapshot of estimated
active-context usage. It delegates to Pi's native `ctx.getContextUsage()` once rather than reading
session files or reconstructing model limits. It is a tool, not a Workcell command or Pi slash command.

## Enable or disable

The tool is enabled by default on Workcell Pi launches, independently of notifications:

```bash
workcell pi run
```

It works in TUI, print (`--print`), JSON (`--mode json`), and RPC (`--mode rpc`) modes without UI
interaction. Other Workcell harnesses are unaffected; no new configuration flag is required.

Forward Pi's tool-selection options after Workcell's `--`:

```bash
# Disable the getter
workcell pi run -- --exclude-tools get_context_usage

# Include the getter in an allowlist
workcell pi run -- --tools read,get_context_usage

# An allowlist omitting the getter disables it
workcell pi run -- --tools read
```

`--tools` replaces the default selection, so name every tool you want. Allowlisting only
`get_context_usage` enables this getter without the default file/shell tools. `--no-tools` disables
it; `--no-builtin-tools` disables default built-ins but retains this extension tool. These selections
remain authoritative after `/reload`; the extension does not re-enable an excluded getter.

Workcell explicitly loads `/opt/workcell/pi-extensions/context-usage.ts`, so `--no-extensions`
disables extension discovery but **does not disable this bundled extension**. Use tool exclusion
instead. For example, this still enables the getter:

```bash
workcell pi run -- --no-extensions --tools get_context_usage
```

## Tool call and result

No parameters are accepted. Example model tool call:

```typescript
get_context_usage({});
```

Extra properties fail Pi's argument validation. Every successful result has exactly three required
fields, each a number or `null`:

| Field | Meaning |
|-------|---------|
| `tokens` | Pi's estimated active-context token count, or `null` when unknown. |
| `contextWindow` | Pi's applicable context-window limit, or `null` when native usage is unavailable. |
| `percent` | Pi's percentage of that window used, or `null` when unknown. |

Example measured snapshot:

```json
{"tokens":4000,"contextWindow":32000,"percent":12.5}
```

Unknown usage with a known limit, such as immediately after compaction before fresh valid assistant
usage is available:

```json
{"tokens":null,"contextWindow":32000,"percent":null}
```

Unavailable native usage, for example when no positive context-window limit is available:

```json
{"tokens":null,"contextWindow":null,"percent":null}
```

Unknown is not zero. A genuine empty-session reading remains:

```json
{"tokens":0,"contextWindow":32000,"percent":0}
```

The example limit is illustrative, not hard-coded. Numbers are preserved exactly as Pi reports
them, without rounding or clamping; fractional percentages and values above 100 remain visible.
Native `undefined` maps to the all-null snapshot, which is successful, not a tool error. Unexpected
native errors use Pi's normal tool-error handling rather than being disguised as unavailable usage.

### Reading the snapshot

- This is an **estimate at execution time**, not cumulative session tokens, billing usage, or the
  compaction trigger threshold. Pi owns provider-usage and heuristic estimates, active-branch
  projection, and post-compaction freshness; abandoned branches are not summed into the count.
- The snapshot excludes this tool's own result and later responses. Ordinary tool calls/results
  and model continuations add context, so a later footer can differ through transcript growth and
  display rounding. Repeated inspection is not free of normal provider usage.
- For virtual selections, native accounting uses the limits of the physical model that produced
  the latest response, not necessarily the selected virtual model's declared limits. Without such
  a response, Pi uses the virtual model's declared limits if available. The tool does not predict
  the router's next physical model.
- The getter does not request compaction, switch models, change effort/settings, or make nested
  model requests. Pi's ordinary continuation and automatic-compaction policies remain unchanged.
  See [Pi self-compaction](pi-self-compaction.md) for the separate compaction tool and
  [Pi reasoning effort](pi-reasoning-effort.md) for model/effort controls.

The model receives compact JSON text. The same payload is returned as schema-backed
`structuredContent` and `details`. While the getter is active, another extension tool can call it
through its execution context:

```typescript
const result = await ctx.executeTool("get_context_usage", {});
const snapshot = result.structuredContent;
```

When codemode is separately enabled, `tools.get_context_usage({})` resolves to the structured
snapshot rather than JSON text. Disabled tools are not made callable by this extension.

## Installation and automated checks

The extension is image-owned, not copied into user extensions or settings. After pulling its
changes, rebuild with `workcell pi build` and start a new container. Updating only the persisted Pi
CLI does not install these image-owned files; use `workcell pi update` separately if its APIs need
updating. See [Persistence](persistence.md#image-baked-tools-and-volume-backed-harness-installs).

Tested with **Pi 1.0.3 and 1.0.4** using their real SDKs. Compatibility with other versions is not
assumed. The focused context-usage suite passed **20 scenarios on each version**, and image-split
checks including relocated extension loading passed **22 tests on each**. The full Pi regression
inventory passed **183 tests on Pi 1.0.4**; launcher checks passed **26 tests**.

From the repository root, with Python, Node supporting `--experimental-import-meta-resolve`, and
Pi installed:

```bash
python -m unittest discover -s tests -p 'test_pi_context_usage.py'
python -m unittest discover -s tests -p 'test_pi_*.py'
python -m unittest discover -s tests -p 'test_run_sandbox_launcher.py'
python -m unittest discover -s tests -p 'test_sandbox_image_split.py'
git diff --check
```

SDK discovery follows the Pi executable on `PATH`, including its selected managed release.
To select another installed SDK, set `PI_TEST_PACKAGE_ROOT` to its
`@earendil-works/pi-coding-agent` package directory, not an install/release root:

```bash
PI_TEST_PACKAGE_ROOT=/path/to/installed/pi-package \
  python -m unittest discover -s tests -p 'test_pi_context_usage.py'
```

An invalid override fails. Genuine SDK absence skips SDK-dependent checks; a skipped suite does
not establish acceptance.

SDK checks isolate user credentials/resources and forbid network. They exercise actual extension
loading, native snapshots and tool dispatch, strict schemas, zeros, heuristic/trailing estimates,
unknown/recovered usage, unavailable limits, fractional/over-window values, active branches, routed
limits, nested access, mode bindings, and selection after reload. Provider responses for dispatch
are scripted; cold/post-compaction snapshots use genuine bound extension contexts without a model
request. Seeded compaction history is not live summarization.

Launcher checks capture fake-Docker command arguments; packaging checks load relocated Dockerfile
COPY outputs. SDK mode bindings are not physical terminal or end-to-end protocol acceptance.
**No Docker build, live TUI, or live-provider acceptance was run for this change.**

## Final host/live acceptance

On a Docker-capable host, use a disposable workspace and non-sensitive conversation. Obtain
permission for host actions and live calls; live calls incur normal provider usage.

1. Rebuild with `workcell pi build`, check Pi with `workcell pi run -- --version`, and start a new
   container. Record image/Pi/Node versions; updating persisted Pi alone does not install the getter.
2. Ask the agent to call `get_context_usage` once and stop without touching files. Check availability
   and a plausible snapshot against Pi's native context display, allowing later transcript growth
   and display rounding. Confirm no requested compaction or model/effort/settings change.
3. Relaunch with `--exclude-tools get_context_usage`, an allowlist without it, and `--no-tools`;
   confirm the getter stays absent after `/reload`. Test `--tools get_context_usage`,
   `--no-builtin-tools`, and `--no-extensions --tools get_context_usage` to confirm it remains
   available in those cases. Test any non-TUI modes you use.
4. Optionally validate native compaction on that disposable session. A model-issued getter usually
   follows a fresh assistant response and may already report numbers, not the immediate unknown
   state. Deterministic SDK snapshot checks cover nulls before fresh valid usage and subsequent
   recovery; a numeric live result is not evidence that the null-state path failed.

Record pass/fail/unexercised results separately from the offline checks before declaring live
acceptance. Do not infer host acceptance from SDK or relocated-file success.
