import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { CompactionState } from "./compact-session-runtime.ts";

const NOTIFICATION = "\x1b]777;notify;Pi;Ready for input\x07";
// Private protocol shared with compact-session-runtime; no runtime dependency when it is absent.
const COMPACTION_STATE_EVENT = "workcell:pi-compaction-state";

export default function terminalNotify(pi: ExtensionAPI): void {
	let currentContext: ExtensionContext | undefined;
	let requestId: string | undefined;
	let unsubscribe: (() => void) | undefined;

	const ready = (ctx: ExtensionContext) => {
		try {
			if (ctx.mode === "tui" && process.stdout.isTTY === true && ctx.isIdle() && !ctx.hasPendingMessages()) {
				process.stdout.write(NOTIFICATION);
			}
		} catch { /* Replaced contexts must not advertise readiness. */ }
	};

	pi.on("session_start", (_event, ctx) => {
		unsubscribe?.();
		currentContext = ctx;
		requestId = undefined;
		unsubscribe = pi.events.on(COMPACTION_STATE_EVENT, (data: unknown) => {
			if (!data || typeof data !== "object") return;
			const state = data as Partial<CompactionState>;
			try {
				if (state.sessionId !== currentContext?.sessionManager.getSessionId() || typeof state.requestId !== "string") return;
			} catch { return; }
			if (state.active === true) { requestId = state.requestId; return; }
			if (state.active !== false || requestId !== state.requestId) return;
			requestId = undefined;
			// Failures have no later native settlement. Success waits for the resumed run's settlement;
			// navigation/reload must never emit a terminal "ready" from the outgoing session.
			if (state.ready === true && (state.outcome === "failed" || state.outcome === "canceled")) ready(currentContext!);
		});
	});
	pi.on("session_shutdown", () => {
		unsubscribe?.(); unsubscribe = undefined;
		currentContext = undefined; requestId = undefined;
	});
	pi.on("agent_settled", (_event, ctx) => {
		if (!requestId) ready(ctx);
	});
}
