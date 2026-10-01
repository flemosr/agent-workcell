import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const [runtimePath, scenario] = process.argv.slice(2);
const { createCompactSessionController, COMPACTION_STATE_EVENT, RESUME_MESSAGE } = await import(pathToFileURL(runtimePath));
const prompt = "  continue the approved slice\nKeep its review gate.  ";
const focus = "  Preserve gates.\nKeep the approved plan.  ";

function harness() {
	let id = "session-1";
	let idle = false;
	let queued = false;
	let stale = false;
	let nextId = 0;
	let signal = new AbortController();
	const entries = [];
	const messages = [];
	const activity = [];
	const notices = [];
	const options = [];
	const ctx = {
		mode: "tui",
		get sessionManager() {
			if (stale) throw new Error("Stale extension context");
			return { getSessionId: () => id, getBranch: () => entries, getEntry: key => entries.find(entry => entry.id === key) };
		},
		get signal() { return signal.signal; },
		isIdle: () => idle,
		hasPendingMessages: () => queued,
		abort: () => { signal.abort(); idle = true; },
		compact: option => { options.push(option); },
		ui: { notify: (text, type) => notices.push({ text, type }), confirm: () => assert.fail("No dialog allowed") },
	};
	const pi = {
		events: { emit: (channel, state) => { assert.equal(channel, COMPACTION_STATE_EVENT); activity.push(state); } },
		sendMessage: (message, option) => {
			messages.push({ message, option });
			entries.push({ ...message, id: `entry-${++nextId}`, type: "custom_message" });
		},
	};
	const controller = createCompactSessionController(pi);
	controller.start(ctx);
	const source = (callId = "call-1", calls = [{ type: "toolCall", id: callId, name: "compact_session", arguments: {} }]) => {
		const entry = { id: `entry-${++nextId}`, type: "message", message: { role: "assistant", content: calls } };
		entries.push(entry);
		return entry;
	};
	async function accept(params = { resumePrompt: prompt, customInstructions: focus }, callId = "call-1") {
		const before = options.length;
		const acknowledgement = await controller.execute(callId, params, signal.signal, ctx);
		assert.equal(acknowledgement.terminate, true);
		assert.equal(acknowledgement.details.status, "queued");
		assert.equal(options.length, before, "execute must not start compaction");
		assert.equal(activity.at(-1).active, true);
		return acknowledgement;
	}
	function finalized(ack, callId = "call-1") {
		const entry = { id: `entry-${++nextId}`, type: "message", message: { role: "toolResult", toolCallId: callId,
			toolName: "compact_session", content: ack.content, details: ack.details, isError: false } };
		entries.push(entry);
		return { toolResults: [entry.message], toolResultEntryIds: [entry.id],
			messageEntryId: entries.findLast(e => e.type === "message" && e.message.role === "assistant").id };
	}
	function success(index = 0) {
		idle = true; signal.abort();
		const compactionEntry = { id: `compaction-${index}`, type: "compaction" };
		entries.push(compactionEntry);
		controller.compacted({ reason: "manual", compactionEntry }, ctx);
		if (scenario === "shared-prefix-branch") entries.pop();
		options[index].onComplete({ summary: "Native summary" });
	}
	function resetSignal() { signal = new AbortController(); idle = false; }
	return { ctx, pi, controller, entries, messages, activity, notices, options, source, accept, finalized, success, resetSignal,
		setQueued: value => queued = value, setIdle: value => idle = value, setId: value => id = value, setStale: value => stale = value };
}

const h = harness();
const source = h.source();
if (scenario.startsWith("invalid-")) {
	const params = { resumePrompt: prompt, customInstructions: focus };
	if (scenario === "invalid-empty") params.resumePrompt = "";
	if (scenario === "invalid-whitespace") params.resumePrompt = " \n\t ";
	if (scenario === "invalid-type") params.resumePrompt = 12;
	if (scenario === "invalid-focus") params.customInstructions = 12;
	if (scenario === "invalid-mixed") source.message.content.push({ type: "toolCall", id: "other", name: "work" });
	if (scenario === "invalid-duplicate") source.message.content.push({ type: "toolCall", id: "other", name: "compact_session" });
	if (scenario === "invalid-origin") h.entries.length = 0;
	if (scenario === "invalid-replay") h.entries.push({ id: "old-result", type: "message", message: { role: "toolResult", toolCallId: "call-1" } });
	if (scenario === "invalid-name") source.message.content[0].name = "work";
	if (scenario === "invalid-mode") h.ctx.mode = "rpc";
	if (scenario === "invalid-session") h.setId("session-2");
	if (scenario === "invalid-aborted") h.ctx.abort();
	await assert.rejects(() => h.accept(params));
	assert.equal(h.activity.length, 0);
	assert.equal(h.options.length, 0);
} else if (scenario.startsWith("loop-")) {
	h.entries.unshift({ id: "resume-old", type: "custom_message", customType: RESUME_MESSAGE });
	if (scenario === "loop-user") h.entries.splice(1, 0, { id: "user-new", type: "message", message: { role: "user" } });
	if (scenario === "loop-work" || scenario === "loop-failed-work") h.entries.splice(1, 0, { id: "work-new", type: "message", message: { role: "toolResult", toolName: "work", isError: scenario === "loop-failed-work" } });
	// Reconstructing on session start/reload must not clear the branch-derived guard or replay jobs.
	h.controller.start(h.ctx);
	if (["loop-immediate", "loop-failed-work"].includes(scenario)) await assert.rejects(() => h.accept(), /immediately/);
	else await h.accept();
	assert.equal(h.options.length, 0);
} else {
	if (scenario === "queued") h.setQueued(true);
	const ack = await h.accept(scenario === "empty-optional" ? { resumePrompt: prompt, customInstructions: " \n " } : undefined);
	if (scenario === "pending-duplicate") {
		await assert.rejects(() => h.accept(), /pending/);
		assert.equal(h.activity.length, 1);
	} else {
		const event = h.finalized(ack);
		if (scenario === "changed-result") event.toolResults[0].details = { requestId: "wrong", status: "queued" };
		if (scenario === "failed-result") event.toolResults[0].isError = true;
		if (scenario === "missing-result") event.toolResultEntryIds = ["missing"];
		if (scenario === "wrong-source") event.messageEntryId = "wrong";
		if (scenario === "cancel-accepted") h.controller.interrupt(h.ctx);
		if (scenario === "start-no-abort") { h.controller.start(h.ctx); assert.equal(h.ctx.signal.aborted, false); }
		if (scenario === "branch-before") h.entries.splice(0, 1);
		if (scenario === "synchronous-throw") h.ctx.compact = () => { throw new Error("Native schedule failed"); };
		if (scenario === "unrelated-turn") {
			h.controller.turnEnd({ ...event, toolResults: [] }, h.ctx);
			assert.equal(h.options.length, 0);
		}
		h.controller.turnEnd(event, h.ctx);
		if (["changed-result", "failed-result", "missing-result", "wrong-source", "cancel-accepted", "start-no-abort", "branch-before", "synchronous-throw"].includes(scenario)) {
			assert.equal(h.options.length, 0);
			assert.equal(h.activity.at(-1).active, false);
		} else {
			assert.equal(h.options.length, 1);
			assert.equal(h.options[0].customInstructions, scenario === "empty-optional" ? undefined : focus);
			h.controller.turnEnd(event, h.ctx);
			assert.equal(h.options.length, 1, "duplicate boundary must not schedule twice");
			if (["cancel-summary", "cancel-handoff"].includes(scenario)) h.controller.interrupt(h.ctx);
			if (scenario === "invalidate") h.controller.invalidate(h.ctx);
			if (scenario === "tree-no-abort") { h.controller.invalidate(h.ctx, { abort: false }); assert.equal(h.ctx.signal.aborted, false); }
			if (scenario === "session-after") h.setId("session-2");
			if (scenario === "branch-after") h.entries.splice(1, 1);
			if (scenario === "stale" || scenario === "disposed-bus") h.setStale(true);
			if (scenario === "disposed-bus") h.pi.events.emit = () => { throw new Error("Stale Pi API"); };
			if (scenario === "native-abort") h.controller.compactFailed({ reason: "manual", aborted: true });
			if (scenario === "cancel-summary" || scenario === "invalidate") {
				assert.deepEqual(h.controller.beforeCompact({ reason: "manual" }, h.ctx), { cancel: true });
			}
			if (scenario === "reentrant") {
				const original = h.pi.sendMessage;
				h.pi.sendMessage = (...args) => { h.options[0].onComplete({}); original(...args); };
			}
			if (scenario === "send-throw") h.pi.sendMessage = () => { throw new Error("Dispatch failed"); };
			if (["failure", "native-abort"].includes(scenario)) { h.setIdle(true); h.options[0].onError(new Error("Native summary failed")); }
			else h.success();
			h.options[0].onComplete({}); h.options[0].onError(new Error("Late error"));
			const suppressed = ["cancel-summary", "cancel-handoff", "invalidate", "tree-no-abort", "shared-prefix-branch", "session-after", "branch-after", "stale", "disposed-bus", "native-abort", "failure", "send-throw"].includes(scenario);
			assert.equal(h.messages.length, suppressed ? 0 : 1);
			if (!suppressed) {
				assert.deepEqual(h.messages[0].option, { triggerTurn: true });
				assert.equal(h.messages[0].message.content[0].text, prompt);
				assert.equal(h.messages[0].message.customType, RESUME_MESSAGE);
				assert.equal(h.messages[0].message.display, true);
				assert.equal(h.activity.at(-1).outcome, "resumed");
				assert.equal(h.activity.at(-1).ready, false, "wait for native resumed settlement");
			}
			assert.equal(h.activity.length, scenario === "disposed-bus" ? 1 : 2, "duplicate/stale callbacks never repeat activity");
			if (scenario === "late-old-callback") {
				h.resetSignal(); h.source("call-2");
				h.entries.splice(-1, 0, { id: "new-user", type: "message", message: { role: "user" } });
				const second = await h.accept(undefined, "call-2");
				h.options[0].onComplete({}); h.options[0].onError(new Error("Stale callback"));
				assert.equal(h.activity.at(-1).active, true, "old callback must not clear new request");
				h.controller.turnEnd(h.finalized(second, "call-2"), h.ctx); h.success(1);
				assert.equal(h.messages.length, 2);
			}
			if (["failure", "native-abort"].includes(scenario)) assert.equal(h.activity.at(-1).ready, true);
		}
	}
}
process.stdout.write(JSON.stringify({ scenario, passed: true, resumes: h.messages.length, nativeSchedules: h.options.length }));
