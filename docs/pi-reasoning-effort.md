# Pi Model Information And Reasoning Effort

Workcell bundles two model-callable Pi tools: `get_model_info` inspects the selected model and
available effort choices; `set_reasoning_effort` changes the selected effort for subsequent requests.
Neither tool switches the selected model/provider or changes startup defaults. They are tools, not
Workcell commands or Pi slash commands.

## Enable or disable

Both tools are enabled by default on Workcell Pi launches, independently of notifications:

```bash
workcell pi run
```

They work in TUI, print (`--print`), JSON, and RPC modes, and support any active model that advertises
one of the accepted effort levels. Models without supported choices can still use the getter.
Other Workcell harnesses are unaffected; no new configuration flag is required.

To keep inspection but disable agent-selected effort changes:

```bash
workcell pi run -- --exclude-tools set_reasoning_effort
```

To disable both tools:

```bash
workcell pi run -- --exclude-tools get_model_info,set_reasoning_effort
```

Pi's `--tools` allowlists and `--no-tools` remain authoritative, including after `/reload`.
`--no-builtin-tools` disables default built-ins, not these extension tools. Workcell explicitly loads
`/opt/workcell/pi-extensions/reasoning-effort.ts`, so `--no-extensions` disables discovery but does
**not** disable this bundled extension; use tool exclusion instead.

## `get_model_info`

No parameters. Example model tool call:

```typescript
get_model_info({});
```

Example result for the current `openai-codex/gpt-6.1-sol` catalog entry:

```json
{
  "model": {
    "provider": "openai-codex",
    "id": "gpt-6.1-sol"
  },
  "currentEffort": "xhigh",
  "availableEffortLevels": ["low", "medium", "high", "xhigh", "max"]
}
```

The getter returns JSON text and matching schema-backed structured content. It is read-only and
can also be called through codemode or nested tool execution while active.

- `model` identifies the currently **selected** Pi model/provider. It is `null` if no model is
  available; it does not predict a virtual router's next physical model.
- `currentEffort` is Pi's current selected thinking level, read at execution time rather than from
  startup environment variables. It can be a native label such as `off` or `minimal` even though
  this setter does not accept those labels.
- `availableEffortLevels` is exactly the active model's supported subset of `low`, `medium`, `high`,
  `xhigh`, and `max`. It is empty when there are no supported choices. The getter and setter share
  capability filtering so discovery and validation agree.

Choices come from Pi's model metadata, not a live capability probe; catalogs and provider support
can change. The list describes this tool's accepted levels, not every native `/thinking` option or
a guarantee that an account/provider will accept the next request.

## `set_reasoning_effort`

One required parameter, `level`, chosen from the getter's non-empty list. No reason, model, provider,
or other input is accepted. Example model tool call:

```typescript
set_reasoning_effort({ level: "low" });
```

The result reports the previous and effective new selection, for example `xhigh -> low`. It also
states that the change applies to the next model request.

- The response issuing the call keeps its original effort. The automatic model continuation after
  the tool result uses the updated selection; an in-flight response cannot be changed retroactively.
- Unsupported choices fail without mutation rather than silently using Pi's clamping. Invalid
  input also fails schema validation. An empty getter list means the agent should not call the setter.
- `off` and `minimal` are excluded from this setter's vocabulary. For the initial GPT target, `off`
  is unsupported and `minimal` aliases `low`; native Pi controls remain separate.
- Pi records actual changes in its native session history. Reopening a persistent session restores
  the selection; repeating the current value succeeds without adding a redundant change entry.
  New-session defaults are untouched.
- The setter is model-only and sequential: it cannot be invoked through codemode/nested execution,
  and batched setter calls execute in call order. The getter is directly callable.

Provider mappings still apply. For virtual models, the selected thinking level is an input to the
router, which owns the dispatched physical model and effort; selected and physical effort can differ.
The tools do not implement routing or expose model selection. This is a tool-interface boundary,
not a sandbox-wide restriction on arbitrary code execution.

Agents are guided to inspect choices first and change effort at meaningful work boundaries, not
repeatedly without doing work. The session's first response uses its configured initial effort.
Self-selection does not guarantee lower cost, lower latency, or better quality. The tools make no
nested model requests, but ordinary prompts and automatic continuations incur normal provider usage.

## Installation and automated checks

The extension is image-owned, not copied into user extensions or settings. After pulling its
changes, rebuild with `workcell pi build` and start a new container. Updating the persisted Pi CLI
is separate; use `workcell pi update` if needed. See
[Persistence](persistence.md#image-baked-tools-and-volume-backed-harness-installs).

Tested with **Pi 1.0.3** and its real managed-install SDK. Compatibility with other versions is not
assumed. The effort SDK suite uses real extension loading, tool execution, capability validation,
settings, persistent sessions, reopening, and a registered virtual router. Only provider responses
are scripted in those sessions; network is forbidden and user credentials/resources are isolated.

From the repository root, with Python, Node supporting `--experimental-import-meta-resolve`, and Pi
installed:

```bash
python -m unittest discover -s tests -p 'test_pi_reasoning_effort.py'
python -m unittest discover -s tests -p 'test_run_sandbox_launcher.py'
python -m unittest discover -s tests -p 'test_sandbox_image_split.py'
```

The SDK suite covers all five levels, getter/setter agreement, next-request timing, persistence,
no-op/cancellation/sequential behavior, aliases and invalid inputs, restricted/non-reasoning models,
virtual selections, modes, and exclusions after reload. Launcher checks use the existing Docker
command-capture harness to verify exact user arguments and unchanged other harnesses. Packaged
acceptance runs the real SDK scenarios against relocated Dockerfile COPY outputs without user
resources. These checks are **not a Docker build or live provider/TUI test**.

SDK discovery follows the Pi executable on `PATH`, including its selected managed release.
`PI_TEST_PACKAGE_ROOT=/path/to/installed/pi-package` can select another installed
`@earendil-works/pi-coding-agent` package; an invalid override fails. Genuine SDK absence skips the
SDK checks, and a skipped suite does not establish acceptance.

## Final host/live acceptance

On a Docker-capable host, use a disposable workspace and non-sensitive conversation. Live calls
incur normal provider usage and require permission to use the configured account.

1. Rebuild with `workcell pi build`; check Pi with `workcell pi run -- --version`. Start a persistent
   session, for example:
   `workcell pi run -- --provider openai-codex --model gpt-6.1-sol --thinking high`.
2. Ask the agent to call `get_model_info` and stop without touching files. Verify the selected
   model/provider, current effort, and available choices against Pi's native selection.
3. Ask it to select an advertised different level, such as `low`, then inspect again and stop.
   Verify the changed selection and successful subsequent provider response, without changing the
   selected model or startup defaults.
4. Attempt an unsupported choice and inspect again; verify a failed tool result and unchanged
   selection. If the model declines to issue an invalid call, record that error-path check as
   unexercised rather than passed; deterministic SDK tests cover the validation path.
5. Exit and resume with `workcell pi run -- --resume`, without a `--thinking` override. Verify the
   saved selection, and verify a separate new session still uses the original configured default.
6. Relaunch with the exclusion examples and confirm disabled tools stay absent, including after
   `/reload`. Test any non-TUI modes you use. Optionally inspect a non-reasoning model and verify an
   empty choice list.

Record image/Pi/Node versions and results before approving live acceptance. Offline success alone
is not evidence that these host or live checks ran.
