import { Type } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { getKeybindings, isKeyRelease } from "@earendil-works/pi-tui";
import { COMPACT_TOOL, createCompactSessionController } from "./compact-session-runtime.ts";

export default function compactSession(pi: ExtensionAPI): void {
	const controller = createCompactSessionController(pi);
	let unsubscribeTerminal: (() => void) | undefined;
	const detach = () => { unsubscribeTerminal?.(); unsubscribeTerminal = undefined; };

	pi.registerTool({
		name: COMPACT_TOOL,
		label: "Compact session",
		description: "Compact this active Pi TUI session using native lossy summarization, then automatically resume the same session once with your exact resumePrompt. Invoke alone in a tool batch. The acknowledgement only queues work: compaction starts after the finalized tool result, and failure/interruption never resumes. No human confirmation is requested. Queued user input retains native steering/follow-up behavior after resume. customInstructions optionally focuses the summary; it is not the continuation or guaranteed retention. Preserve existing review, approval and commit gates; do not use this tool to bypass them.",
		promptSnippet: "Compact the active TUI session and automatically continue with an agent-authored prompt.",
		promptGuidelines: [
			"Use compact_session alone, only at an approved work boundary. Supply a specific non-empty resumePrompt preserving pending review/approval/commit gates; successful compaction resumes it without human intervention.",
			"Native compaction is lossy. Optional customInstructions guides summarization, not retention budgets or the separate split-turn-prefix summary. Persist important approved plans normally before compacting.",
			"Do not immediately compact again or automatically retry after failure. Complete another tool or receive new user input before another self-compaction. The queued acknowledgement is not a completed summary.",
		],
		exposure: "model-only",
		executionMode: "sequential",
		parameters: Type.Object({
			resumePrompt: Type.String({ minLength: 1, description: "Exact agent-authored continuation after successful compaction; preserve pending workflow gates." }),
			customInstructions: Type.Optional(Type.String({ description: "Optional native summarization focus, separate from resumePrompt." })),
		}),
		execute: (toolCallId, params, signal, _onUpdate, ctx) => controller.execute(toolCallId, params, signal, ctx),
	});

	pi.on("session_start", (_event, ctx) => {
		detach();
		controller.start(ctx);
		if (ctx.mode !== "tui") {
			pi.setActiveTools(pi.getActiveTools().filter(name => name !== COMPACT_TOOL));
			return;
		}
		// Never add it here: native --tools/--no-tools/--exclude-tools selection stays authoritative.
		unsubscribeTerminal = ctx.ui.onTerminalInput(data => {
			if (!isKeyRelease(data) && getKeybindings().matches(data, "app.interrupt")) controller.interrupt(ctx);
			// Leave native editor/autocomplete/abort routing intact. Earlier raw consumers can intercept it.
		});
	});
	pi.on("session_shutdown", (_event, ctx) => { detach(); controller.invalidate(ctx); });
	pi.on("session_before_switch", (_event, ctx) => controller.invalidate(ctx));
	pi.on("session_before_fork", (_event, ctx) => controller.invalidate(ctx));
	// Native tree navigation rejects active compaction first. At handoff, invalidate dispatch
	// without aborting the navigation's own branch-summary controller.
	pi.on("session_before_tree", (_event, ctx) => controller.invalidate(ctx, { abort: false }));
	// Required even when no other extension observes input: native preflight yields the TUI queue
	// behind callback dispatch. Never consume/cancel ordinary text; loop admission reads persisted history.
	pi.on("input", () => {});
	pi.on("turn_end", (event, ctx) => controller.turnEnd(event, ctx));
	pi.on("session_before_compact", (event, ctx) => controller.beforeCompact(event, ctx));
	pi.on("session_compact", (event, ctx) => controller.compacted(event, ctx));
	pi.on("session_compact_failed", event => controller.compactFailed(event));
}
