import { pathToFileURL } from "node:url";

const [extensionPath, scenarioJson] = process.argv.slice(2);
if (!extensionPath || !scenarioJson) throw new Error("usage: run_pi_notification_extension.mjs <extension> <scenario-json>");
const scenario = JSON.parse(scenarioJson);
const handlers = new Map();
const listeners = new Set();
const registeredEvents = [];
const writes = [];
const originalWrite = process.stdout.write;
const originalIsTTY = Object.getOwnPropertyDescriptor(process.stdout, "isTTY");
const state = { isIdle: scenario.isIdle, hasPendingMessages: scenario.hasPendingMessages ?? false };
let ctx;
const context = sessionId => ({
	mode: scenario.mode,
	isIdle: () => state.isIdle,
	hasPendingMessages: () => state.hasPendingMessages,
	sessionManager: { getSessionId: () => sessionId },
});
Object.defineProperty(process.stdout, "isTTY", { configurable: true, value: scenario.isTTY });
process.stdout.write = (chunk, encoding) => { writes.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk, encoding)); return true; };
try {
	const { default: register } = await import(pathToFileURL(extensionPath).href);
	register({
		on(event, handler) { registeredEvents.push(event); handlers.set(event, handler); },
		events: { on(channel, handler) {
			if (channel !== "workcell:pi-compaction-state") throw new Error("Unexpected channel");
			listeners.add(handler); return () => listeners.delete(handler);
		} },
	});
	ctx = context("session-1");
	await handlers.get("session_start")?.({ type: "session_start" }, ctx);
	const steps = scenario.steps ?? Array.from({ length: scenario.invocations ?? 1 }, () => ({ kind: "settled" }));
	for (const step of steps) {
		if (step.isIdle !== undefined) state.isIdle = step.isIdle;
		if (step.hasPendingMessages !== undefined) state.hasPendingMessages = step.hasPendingMessages;
		if (step.kind === "settled") await handlers.get("agent_settled")?.({ type: "agent_settled" }, ctx);
		if (step.kind === "activity") for (const listener of [...listeners]) await listener(step.state);
		if (step.kind === "start") {
			ctx = context(step.sessionId ?? "session-1");
			await handlers.get("session_start")?.({ type: "session_start" }, ctx);
		}
		if (step.kind === "shutdown") await handlers.get("session_shutdown")?.({ type: "session_shutdown" }, ctx);
	}
} finally {
	process.stdout.write = originalWrite;
	if (originalIsTTY) Object.defineProperty(process.stdout, "isTTY", originalIsTTY);
	else delete process.stdout.isTTY;
}
process.stdout.write(JSON.stringify({ registeredEvents, listeners: listeners.size, writes: writes.map(write => write.toString("base64")) }));
