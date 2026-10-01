import { randomUUID } from "node:crypto";
import type {
	ExtensionAPI,
	ExtensionContext,
	SessionBeforeCompactEvent,
	SessionCompactFailedEvent,
	SessionCompactEvent,
	TurnEndEvent,
} from "@earendil-works/pi-coding-agent";

export const COMPACT_TOOL = "compact_session";
export const RESUME_MESSAGE = "workcell.compaction.resume";
export const COMPACTION_STATE_EVENT = "workcell:pi-compaction-state";

export type CompactionState = {
	sessionId: string;
	requestId: string;
	active: boolean;
	outcome?: "resumed" | "failed" | "canceled" | "invalidated";
	ready?: boolean;
};

export type CompactParameters = { resumePrompt: string; customInstructions?: string };
type Request = CompactParameters & {
	requestId: string;
	toolCallId: string;
	sourceId: string;
	sessionId: string;
	generation: number;
	resultId?: string;
	compactionId?: string;
	canceled: boolean;
	phase: "accepted" | "scheduled" | "summarizing" | "dispatching";
};

function queuedDetails(details: unknown, request: Request): boolean {
	return typeof details === "object" && details !== null &&
		"requestId" in details && details.requestId === request.requestId &&
		"status" in details && details.status === "queued";
}

/** Ephemeral transition state only. Pi owns summarization, history, queues and billing. */
export function createCompactSessionController(pi: Pick<ExtensionAPI, "events" | "sendMessage">) {
	let generation = 0;
	let sessionId: string | undefined;
	let pending: Request | undefined;
	// Retain canceled native ownership until its callback, even after navigation invalidates dispatch.
	let scheduled: Request | undefined;

	function current(request: Request, ctx: ExtensionContext): boolean {
		try {
			if (pending !== request || request.generation !== generation || ctx.mode !== "tui" ||
				ctx.sessionManager.getSessionId() !== request.sessionId) return false;
			const branch = ctx.sessionManager.getBranch();
			return branch.some(entry => entry.id === request.sourceId) &&
				(!request.resultId || branch.some(entry => entry.id === request.resultId)) &&
				(!request.compactionId || branch.some(entry => entry.id === request.compactionId));
		} catch {
			return false; // Disposed/replaced contexts are deliberately guarded by Pi.
		}
	}

	function finish(request: Request, ctx: ExtensionContext, outcome: NonNullable<CompactionState["outcome"]>) {
		if (scheduled === request) scheduled = undefined;
		if (pending !== request) return;
		let ready = false;
		try {
			ready = outcome !== "resumed" && outcome !== "invalidated" && current(request, ctx) &&
				ctx.isIdle() && !ctx.hasPendingMessages();
		} catch { /* Stale contexts must never announce readiness. */ }
		pending = undefined;
		publish({ sessionId: request.sessionId, requestId: request.requestId, active: false, outcome, ready });
	}

	function invalidate(ctx: ExtensionContext, { abort = true } = {}) {
		const request = pending;
		if (request) {
			request.canceled = true;
			finish(request, ctx, "invalidated");
			// A scheduled native operation still needs the canceled flag at its pre-compaction hook.
			if (request.phase === "scheduled" || request.phase === "summarizing") scheduled = request;
			if (abort) try { ctx.abort(); } catch { /* Already disposed. */ }
		}
		generation++;
	}

	function start(ctx: ExtensionContext) {
		invalidate(ctx, { abort: false }); // Never abort a newly bound session using its fresh context.
		sessionId = ctx.sessionManager.getSessionId();
	}

	function interrupt(ctx: ExtensionContext): boolean {
		if (!pending || !current(pending, ctx)) return false;
		pending.canceled = true;
		ctx.abort(); // Native TUI abort also restores queued text; never consume the key.
		return true;
	}

	async function execute(toolCallId: string, params: CompactParameters, signal: AbortSignal | undefined, ctx: ExtensionContext) {
		if (ctx.mode !== "tui") throw new Error("compact_session is available only in Pi's interactive TUI.");
		const currentSessionId = ctx.sessionManager.getSessionId();
		if (currentSessionId !== sessionId) throw new Error("The session changed; do not replay a compaction request.");
		if (signal?.aborted || ctx.signal?.aborted) throw new Error("The operation was canceled.");
		if (pending || scheduled) throw new Error("A session compaction request is already pending.");
		if (typeof params.resumePrompt !== "string" || !params.resumePrompt.trim()) throw new Error("resumePrompt must be a non-empty string.");
		if (params.customInstructions !== undefined && typeof params.customInstructions !== "string") throw new Error("customInstructions must be a string.");

		const branch = ctx.sessionManager.getBranch();
		const sourceIndex = branch.findLastIndex(entry => entry.type === "message" && entry.message.role === "assistant" &&
			entry.message.content.some(block => block.type === "toolCall" && block.id === toolCallId));
		const source = branch[sourceIndex];
		if (!source || source.type !== "message" || source.message.role !== "assistant") throw new Error("Cannot establish the finalized originating assistant tool call.");
		const calls = source.message.content.filter(block => block.type === "toolCall");
		if (calls.length !== 1 || calls[0].name !== COMPACT_TOOL) throw new Error("Call compact_session alone, not alongside other tools or another compaction.");
		if (branch.slice(sourceIndex + 1).some(entry => entry.type === "message" && entry.message.role === "toolResult" && entry.message.toolCallId === toolCallId)) {
			throw new Error("This tool call already has a finalized result; do not replay it.");
		}
		// Re-derive from the active raw branch, including on reload/navigation. Merely observing
		// typing or an input consumed by another extension is not evidence of completed work.
		const resumeIndex = branch.findLastIndex(entry => entry.type === "custom_message" && entry.customType === RESUME_MESSAGE);
		if (resumeIndex >= 0 && !branch.slice(resumeIndex + 1, sourceIndex).some(entry => entry.type === "message" &&
			(entry.message.role === "user" || (entry.message.role === "toolResult" && entry.message.toolName !== COMPACT_TOOL && !entry.message.isError)))) {
			throw new Error("Do not compact again immediately: complete a non-compaction tool or receive new user input first.");
		}

		const request: Request = { ...params, requestId: randomUUID(), toolCallId, sourceId: source.id,
			sessionId: currentSessionId, generation, canceled: false, phase: "accepted" };
		pending = request;
		publish({ sessionId: currentSessionId, requestId: request.requestId, active: true });
		return {
			content: [{ type: "text" as const, text: "Compaction queued. After native compaction succeeds, this same session will resume once with the supplied prompt. Failure or interruption will not resume it." }],
			details: { requestId: request.requestId, status: "queued" as const },
			terminate: true,
		};
	}

	function turnEnd(event: TurnEndEvent, ctx: ExtensionContext) {
		const request = pending;
		if (!request || request.phase !== "accepted") return;
		const index = event.toolResults.findIndex(result => result.toolCallId === request.toolCallId);
		if (index < 0) return;
		if (!current(request, ctx)) { finish(request, ctx, "invalidated"); return; }
		if (request.canceled || ctx.signal?.aborted) { finish(request, ctx, "canceled"); return; }
		const result = event.toolResults[index];
		const resultId = event.toolResultEntryIds[index];
		const entry = resultId ? ctx.sessionManager.getEntry(resultId) : undefined;
		if (event.messageEntryId !== request.sourceId || result.isError || result.toolName !== COMPACT_TOOL ||
			!queuedDetails(result.details, request) || entry?.type !== "message" || entry.message.role !== "toolResult" ||
			entry.message.toolCallId !== request.toolCallId || entry.message.isError || !queuedDetails(entry.message.details, request)) {
			finish(request, ctx, "failed");
			notify(ctx, "Self-compaction was not scheduled: its queued acknowledgement was changed or not finalized.", "warning");
			return;
		}
		request.resultId = resultId;
		if (!current(request, ctx)) { finish(request, ctx, "invalidated"); return; }
		request.phase = "scheduled";
		scheduled = request;
		try {
			// Never await here: native compact() aborts and waits for this active boundary to finish.
			ctx.compact({
				customInstructions: request.customInstructions?.trim() ? request.customInstructions : undefined,
				onComplete: () => {
					if (scheduled === request) scheduled = undefined;
					if (pending !== request || request.phase === "dispatching") return;
					if (!request.compactionId || !current(request, ctx)) { finish(request, ctx, "invalidated"); return; }
					if (request.canceled) { finish(request, ctx, "canceled"); return; }
					// The initiating signal is normally aborted by compaction; it is NOT an interrupt latch.
					request.phase = "dispatching"; // Claim exactly once before sendMessage or reentrant callbacks.
					try {
						pi.sendMessage({ customType: RESUME_MESSAGE, content: [{ type: "text", text: request.resumePrompt }],
							display: true, details: { requestId: request.requestId } }, { triggerTurn: true });
						finish(request, ctx, "resumed");
					} catch (error) { failed(request, ctx, error); }
				},
				onError: error => failed(request, ctx, error),
			});
		} catch (error) { failed(request, ctx, error); }
	}

	function failed(request: Request, ctx: ExtensionContext, error: unknown) {
		if (scheduled === request) scheduled = undefined;
		if (pending !== request) return;
		if (!current(request, ctx)) { finish(request, ctx, "invalidated"); return; }
		finish(request, ctx, request.canceled ? "canceled" : "failed");
		notify(ctx, request.canceled ? "Self-compaction canceled; no automatic continuation." :
			`Self-compaction failed; no automatic continuation: ${error instanceof Error ? error.message : String(error)}`, request.canceled ? "info" : "error");
	}

	function publish(state: CompactionState) {
		try { pi.events.emit(COMPACTION_STATE_EVENT, state); } catch { /* A disposed Pi API is guarded too. */ }
	}

	function notify(ctx: ExtensionContext, text: string, level: "info" | "warning" | "error") {
		try { ctx.ui.notify(text, level); } catch { /* Callback races with disposal must not reject in the background. */ }
	}

	function beforeCompact(event: SessionBeforeCompactEvent, ctx: ExtensionContext) {
		const request = scheduled;
		if (!request || event.reason !== "manual") return;
		try {
			if (ctx.sessionManager.getSessionId() !== request.sessionId) return;
			if (request.canceled || !current(request, ctx)) return { cancel: true as const };
			request.phase = "summarizing";
		} catch { return { cancel: true as const }; }
	}

	function compacted(event: SessionCompactEvent, ctx: ExtensionContext) {
		if (scheduled && event.reason === "manual" && current(scheduled, ctx)) {
			scheduled.compactionId = event.compactionEntry.id;
		}
	}

	function compactFailed(event: SessionCompactFailedEvent) {
		if (scheduled && event.reason === "manual" && event.aborted) scheduled.canceled = true;
	}

	return { start, invalidate, interrupt, execute, turnEnd, beforeCompact, compacted, compactFailed };
}
