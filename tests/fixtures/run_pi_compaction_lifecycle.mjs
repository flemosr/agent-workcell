// Offline integration: load the shipped extension through Pi's real extension loader.
import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { setTimeout as sleep } from "node:timers/promises";

const [rootArgument, extensionArgument, notificationArgument, selectedCase] = process.argv.slice(2);
if (!notificationArgument || !process.execArgv.includes("--experimental-import-meta-resolve")) {
	throw new Error("usage: node --experimental-import-meta-resolve run_pi_compaction_lifecycle.mjs <pi-package-root> <extension> <notifications> [case]");
}
const root = resolve(rootArgument);
const extensionPath = resolve(extensionArgument);
const notificationPath = resolve(notificationArgument);
const isolated = await mkdtemp(join(tmpdir(), "workcell-pi-compaction-"));
process.env.HOME = join(isolated, "home");
process.env.PI_CODING_AGENT_DIR = join(isolated, "global");
process.env.XDG_CACHE_HOME = join(isolated, "cache");
delete process.env.PI_SESSION_FILE;
delete process.env.PI_SESSION_ID;
globalThis.fetch = () => { throw new Error("Network forbidden in offline integration tests"); };
let sdk, ai, tui, packageVersion;
try {
	sdk = await import(pathToFileURL(join(root, "dist/index.js")));
	// Resolve ESM-only host dependencies from Pi, including flattened local npm installs.
	const parent = pathToFileURL(join(root, "package.json")).href;
	ai = await import(import.meta.resolve("@earendil-works/pi-ai", parent));
	tui = await import(import.meta.resolve("@earendil-works/pi-tui", parent));
	packageVersion = JSON.parse(await readFile(join(root, "package.json"), "utf8")).version;
} catch (error) {
	await rm(isolated, { recursive: true, force: true });
	throw error;
}
const { createAgentSession, AgentSessionRuntime, DefaultResourceLoader, SessionManager, SettingsManager, ModelRuntime, InteractiveMode, CustomEditor } = sdk;
const { Type, contentText, createAssistantMessageEventStream, InMemoryCredentialStore } = ai;
const { KeybindingsManager, TUI_KEYBINDINGS, setKeybindings, TuiMainScreen } = tui;
const resumePrompt = "  proceed with the approved slice\nKeep the review gate.  ";
const nextPrompt = "Continue the next approved slice; do not commit.";
const focus = "  Preserve the approved plan and pending review/commit gates.  ";
const QUEUED = "QUEUED_USER_OVERRIDE";
const FINAL = "OFFLINE FINAL";
const notification = "\x1b]777;notify;Pi;Ready for input\x07";
const usage = (input = 0) => ({ input, output: input ? 30 : 0, cacheRead: input ? 10 : 0, cacheWrite: 0,
	totalTokens: input ? input + 40 : 0, cost: { input: input ? 0.001 : 0, output: input ? 0.002 : 0, cacheRead: input ? 0.0001 : 0, cacheWrite: 0, total: input ? 0.0031 : 0 } });
const reports = [];
let trace = [];
let cleanupSession;
let cleanupRenderer;
const originalWrite = process.stdout.write;
const originalTTY = Object.getOwnPropertyDescriptor(process.stdout, "isTTY");

function pairs(entries) {
	const calls = new Set(); const results = new Set();
	for (const entry of entries) {
		if (entry.type !== "message") continue;
		if (entry.message.role === "assistant") for (const block of entry.message.content) if (block.type === "toolCall") calls.add(block.id);
		if (entry.message.role === "toolResult") { assert(calls.has(entry.message.toolCallId), "orphan result"); assert(!results.has(entry.message.toolCallId), "duplicate result"); results.add(entry.message.toolCallId); }
	}
	assert.deepEqual(results, calls, "every finalized call has a result");
}
async function until(predicate, description) {
	for (let i = 0; i < 1500; i++) { if (predicate()) return; await sleep(2); }
	assert.fail(`Timeout: ${description}`);
}

async function runCase(name, options = {}) {
	trace = [];
	const record = (type, data = {}) => trace.push({ index: trace.length, type, ...data });
	const cwd = join(isolated, name);
	const agentDir = join(cwd, "agent");
	await mkdir(agentDir, { recursive: true });
	const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false, reserveTokens: 1000, keepRecentTokens: options.small ? 30000 : 400 },
		retry: { enabled: false }, defaultTools: ["compact_session", "work"], doubleEscapeAction: "none" });
	const modelRuntime = await ModelRuntime.create({ credentials: new InMemoryCredentialStore(), modelsPath: null,
		modelsStorePath: join(cwd, "models-cache.json"), refreshOnCreate: false, allowModelNetwork: false });
	let session;
	let runtime;
	let active = false;
	let summaryActive = false;
	let agentStep = 0;
	let compactions = 0;
	let notifications = 0;
	let nativeInterrupts = 0;
	let terminalKeys = 0;
	let terminalOutcome;
	let injected = false;
	let replacing;
	const callbacks = [];
	const errors = [];
	const replies = [];
	const preparations = [];
	const flushes = [];
	const activity = [];
	const queueItems = options.items ?? [{ text: QUEUED, mode: options.queueMode ?? "steer" }];
	const bindings = new KeybindingsManager({ ...TUI_KEYBINDINGS,
		"app.interrupt": { defaultKeys: "escape", description: "Cancel or abort" },
		"app.exit": { defaultKeys: "ctrl+d", description: "Exit" },
		"app.clipboard.pasteImage": { defaultKeys: "ctrl+v", description: "Paste" },
	}, options.remap ? { "app.interrupt": "ctrl+x" } : {});
	setKeybindings(bindings);
	const terminal = { columns: 100, rows: 30, kittyProtocolActive: false,
		start(callback) { this.input = callback; }, stop() {}, write() {}, drainInput: async () => {},
		moveBy() {}, hideCursor() {}, showCursor() {}, clearLine() {}, clearFromCursor() {}, clearScreen() {}, setTitle() {}, setProgress() {} };
	const renderer = new TuiMainScreen(terminal);
	cleanupRenderer = renderer;
	renderer.requestRender = () => {}; renderer.requestImmediateRender = () => {};
	const identity = value => value;
	const theme = { borderColor: identity, selectList: { selectedPrefix: identity, selectedText: identity, description: identity, scrollInfo: identity, noMatch: identity } };
	class DelegatingEditor extends CustomEditor { handleInput(data) { record("custom_editor"); super.handleInput(data); } }
	const editor = new (options.customEditor ? DelegatingEditor : CustomEditor)(renderer, theme, bindings);
	const mode = Object.create(InteractiveMode.prototype);
	mode.ui = renderer; mode.keybindings = bindings; mode.editor = editor; mode.defaultEditor = editor;
	mode.compactionQueuedMessages = []; mode.extensionTerminalInputSubscriptions = new Set();
	mode.updateEditorBorderColor = () => {}; mode.updatePendingMessagesDisplay = () => record("tui_queue_display");
	mode.showError = text => errors.push(text);
	renderer.addChild(editor); renderer.setFocus(editor); renderer.start();
	if (options.firstListener) renderer.addInputListener(data => {
		record("other_input_listener");
		if (options.consumeFirst && bindings.matches(data, "app.interrupt")) return { consume: true };
	});
	function key(stage) {
		if (injected) return;
		injected = true; terminalKeys++;
		record("terminal_key", { stage, active });
		terminal.input(options.key ?? (options.remap ? "\x18" : "\x1b"));
	}
	Object.defineProperty(process.stdout, "isTTY", { configurable: true, value: options.isTTY ?? true });
	process.stdout.write = (chunk, encoding) => {
		const text = Buffer.isBuffer(chunk) ? chunk.toString() : String(chunk);
		assert.equal(text, notification, "only exact OSC notification bytes may be written");
		notifications++; record("ready", { active, idle: session?.isIdle }); return true;
	};

	function streamSimple(model, context, streamOptions = {}) {
		const stream = createAssistantMessageEventStream();
		const text = context.messages.map(message => typeof message.content === "string" ? message.content : contentText(message.content ?? [])).join("\n");
		const isSummary = summaryActive;
		record("provider_request", { isSummary, text });
		queueMicrotask(async () => {
			let message = { role: "assistant", api: model.api, provider: model.provider, model: model.id, timestamp: Date.now(),
				usage: usage(Math.ceil(text.length / 4) + 100), content: [], stopReason: "pending" };
			try {
				if (isSummary) {
					if (options.queueInput && !injected) { injected = true; mode.compactionQueuedMessages.push(...queueItems); record("tui_input_queued"); }
					if (options.queueRestore && !injected) mode.compactionQueuedMessages.push({ text: "QUEUE_TO_RESTORE", mode: "steer" });
					if (options.stage === "summary") key("summary");
					if (options.abortApi) session.abortCompaction();
					if (options.disposeDirect) session.dispose();
					if (options.noise) for (const data of ["x", "\x1b[<64;10;10M", "\x1b[6;16;8t", "\x1b[27;1:3u"]) terminal.input(data);
					if (options.replace && options.replace !== "tree" && !replacing) {
						record("replacement_requested");
						if (options.replace === "new") replacing = runtime.newSession();
						if (options.replace === "fork") replacing = runtime.fork(seededIds[0], { position: "at" });
						if (options.replace === "switch") replacing = runtime.switchSession(targetSession.sessionManager.getSessionFile());
						if (options.replace === "reload") replacing = session.reload();
						if (options.replace === "shutdown") replacing = runtime.dispose();
					}
					await sleep(2);
					if (streamOptions.signal?.aborted) throw new Error("Native summary interrupted");
					if (options.providerFailure) throw new Error("Scripted provider summary failure");
					message.content = [{ type: "text", text: "## Goal\nContinue the approved task.\n## Next Steps\nKeep review gates.\n" + "Native summary. ".repeat(30) }];
					message.stopReason = "stop";
				} else {
					if (agentStep > 0 && options.slowResume) await sleep(60);
					if (agentStep > 0 && options.stage === "resumed") key("resumed");
					if (streamOptions.signal?.aborted) throw new Error("Native resumed run interrupted");
					const call = (id, name, args) => ({ type: "toolCall", id, name, arguments: args });
					const compact = id => call(id, "compact_session", { resumePrompt: id === "compact-1" ? resumePrompt : nextPrompt, customInstructions: focus });
					if (agentStep === 0) {
						message.content = [compact("compact-1")];
						if (options.badPrompt) message.content[0].arguments.resumePrompt = " \n\t ";
						if (options.mixed) message.content.push(call("work-mixed", "work", {}));
						if (options.duplicate) message.content.push(compact("compact-duplicate"));
						message.stopReason = "toolUse";
					} else if (options.successive && agentStep === 1) {
						message.content = [call("work-1", "work", {})]; message.stopReason = "toolUse";
					} else if ((options.successive && agentStep === 2) || (options.loop && agentStep === 1)) {
						message.content = [compact("compact-2")]; message.stopReason = "toolUse";
					} else { message.content = [{ type: "text", text: FINAL }]; message.stopReason = "stop"; }
					agentStep++;
				}
				stream.push({ type: "start", partial: { ...message, stopReason: "pending" } });
				for (let i = 0; i < message.content.length; i++) {
					const block = message.content[i];
					if (block.type === "text") {
						stream.push({ type: "text_start", contentIndex: i, partial: message });
						stream.push({ type: "text_delta", contentIndex: i, delta: block.text, partial: message });
						stream.push({ type: "text_end", contentIndex: i, content: block.text, partial: message });
					} else {
						stream.push({ type: "toolcall_start", contentIndex: i, partial: message });
						stream.push({ type: "toolcall_delta", contentIndex: i, delta: JSON.stringify(block.arguments), partial: message });
						stream.push({ type: "toolcall_end", contentIndex: i, toolCall: block, partial: message });
					}
				}
				replies.push(message); stream.push({ type: "done", reason: message.stopReason, message });
			} catch (error) {
				message = { ...message, content: [], usage: usage(), stopReason: streamOptions.signal?.aborted ? "aborted" : "error", errorMessage: error.message };
				stream.push({ type: "error", reason: message.stopReason, error: message });
			} finally { stream.end(); }
		});
		return stream;
	}
	modelRuntime.registerProvider("workcell-offline-test", { api: "workcell-offline-test", apiKey: "offline-only", baseUrl: "https://offline.invalid", streamSimple,
		models: [{ id: "scripted", name: "Scripted offline", reasoning: false, input: ["text"], contextWindow: 32000, maxTokens: 2000,
			cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }] });
	const model = modelRuntime.getModel("workcell-offline-test", "scripted");
	// Persist only in this temporary directory for actual switch/fork/reload/runtime tests.
	const sessionManager = SessionManager.create(cwd, join(cwd, "sessions"));
	const seededIds = [];
	if (!options.small) for (let i = 0; i < 8; i++) {
		seededIds.push(sessionManager.appendMessage({ role: "user", content: [{ type: "text", text: `Approved old task ${i}. ` + "old context ".repeat(150) }], timestamp: Date.now() }));
		seededIds.push(sessionManager.appendMessage({ role: "assistant", content: [{ type: "text", text: "Completed old work. ".repeat(100) }],
			provider: model.provider, model: model.id, api: model.api, timestamp: Date.now(), usage: usage(), stopReason: "stop" }));
	}
	let targetSession;
	if (options.replace === "switch") {
		const targetManager = SessionManager.create(cwd, join(cwd, "sessions"));
		targetSession = { sessionManager: targetManager };
		targetManager.appendMessage({ role: "user", content: [{ type: "text", text: "Saved target" }], timestamp: Date.now() });
		targetManager.appendMessage({ role: "assistant", content: [{ type: "text", text: "Saved target answer" }], provider: model.provider,
			model: model.id, api: model.api, timestamp: Date.now(), usage: usage(), stopReason: "stop" });
	}
	function observer(pi) {
		pi.events.on("workcell:pi-compaction-state", state => {
			activity.push(state); active = state.active; terminalOutcome = state.outcome; record("activity", state);
			if (state.active && options.stage === "accepted") key("accepted");
		});
		pi.on("session_start", (_event, ctx) => {
			record("session_start", { mode: ctx.mode });
			const info = pi.getAllTools().find(tool => tool.name === "compact_session");
			assert.equal(info.exposure, "model-only");
			assert(info.promptGuidelines.some(text => text.includes("commit")));
		});
		if (options.delayedInput || options.syncInput) pi.on("input", async event => {
			if (queueItems.some(item => item.text === event.text)) {
				record("earlier_input", { text: event.text }); if (options.delayedInput) await sleep(25);
			}
		});
		pi.on("tool_execution_end", async event => {
			if (event.toolName === "compact_session" && options.preExisting && !injected) {
				injected = true;
				for (const item of queueItems) await session[item.mode === "followUp" ? "followUp" : "steer"](item.text);
			}
		});
		pi.on("tool_result", event => {
			if (options.changedResult && event.toolName === "compact_session") return { details: { requestId: "wrong" } };
		});
		pi.on("session_before_compact", event => {
			preparations.push(event.preparation); record("before_compact");
			assert.equal(event.customInstructions, focus);
			assert.equal(event.preparation.settings.keepRecentTokens, 400);
			if (options.hookCancel) return { cancel: true };
			if (options.hookSummary) return { compaction: { summary: "Hook summary; retain the approved review gate.",
				firstKeptEntryId: event.preparation.firstKeptEntryId, tokensBefore: event.preparation.tokensBefore, usage: usage(55) } };
		});
		pi.on("session_compact", async () => {
			compactions++; record("summary_saved");
			if (options.stage === "persisted") { key("persisted"); await sleep(2); }
			if (options.branchChange) sessionManager.branch(seededIds[0]);
		});
		pi.registerTool({ name: "work", label: "Offline work", description: "Harmless scripted work", parameters: Type.Object({}),
			execute: async (_id, _params, _signal, _update, ctx) => {
				assert(!ctx.tools.some(tool => tool.name === "compact_session"), "model-only cannot be nested");
				return { content: [{ type: "text", text: "Work complete. " + "new slice evidence ".repeat(160) }], details: {} };
			} });
	}
	async function makeSession(manager, sessionStartEvent) {
		const paths = options.notifications === false ? [extensionPath] : options.notifyFirst ? [notificationPath, extensionPath] : [extensionPath, notificationPath];
		const resourceLoader = new DefaultResourceLoader({ cwd, agentDir, settingsManager, additionalExtensionPaths: paths,
			noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
			systemPrompt: "Offline test. Only scripted tools.", extensionFactories: [observer],
			// A preceding external input handler must truly precede the shipped controller's observer.
			extensionsOverride: result => ({ ...result, extensions: [...result.extensions].sort((a, b) =>
				(Number(!a.path.startsWith("inline:")) - Number(!b.path.startsWith("inline:")))) }),
		});
		await resourceLoader.reload();
		assert.deepEqual(resourceLoader.getExtensions().errors, []);
		const created = await createAgentSession({ cwd, agentDir, modelRuntime, model, settingsManager, sessionManager: manager,
			resourceLoader, sessionStartEvent, ...options.selection });
		return { ...created, services: { cwd, agentDir }, diagnostics: [] };
	}
	const created = await makeSession(sessionManager);
	session = created.session;
	cleanupSession = session;
	runtime = new AgentSessionRuntime(session, created.services, async ({ sessionManager: manager, sessionStartEvent }) => makeSession(manager, sessionStartEvent));
	mode.runtimeHost = runtime;
	const originalSession = session;
	const originalId = session.sessionId;
	function subscribe(current) {
		current.subscribe(event => {
			if (["agent_start", "agent_settled", "compaction_start", "compaction_end"].includes(event.type)) record(event.type, { idle: current.isIdle });
			if (event.type === "queue_update") record("queue_update", { steering: [...current.getSteeringMessages()], followUp: [...current.getFollowUpMessages()] });
			if (event.type === "agent_settled" && options.stage === "waiting-idle" && active) key("waiting-idle");
			if (event.type === "compaction_start") {
				summaryActive = true;
				callbacks.push(editor.onEscape);
				// Same native compaction handler; spinner/status rendering deliberately excluded.
				editor.onEscape = () => { nativeInterrupts++; current.abortCompaction(); };
			}
			if (event.type === "compaction_end") {
				summaryActive = false; editor.onEscape = callbacks.pop();
				if (options.stage === "handoff") key("handoff");
				if (options.replace === "tree") replacing = current.navigateTree(seededIds[1]);
				if (options.queueInput) flushes.push(mode.flushCompactionQueue({ willRetry: event.willRetry }));
			}
		});
	}
	const failDialog = () => assert.fail("No human confirmation/input permitted");
	async function bind(current) {
		session = current; cleanupSession = current;
		mode.setupKeyHandlers();
		await current.bindExtensions({ mode: options.mode ?? "tui", abortHandler: () => mode.restoreQueuedMessagesToEditor({ abort: true }),
			uiContext: { onTerminalInput: handler => mode.addExtensionTerminalInputListener(handler), confirm: failDialog, select: failDialog,
				input: failDialog, editor: failDialog, custom: failDialog, setStatus: () => {},
				notify: (text, level) => record("notice", { text, level }) }, onError: error => errors.push(error.error) });
	}
	subscribe(session);
	runtime.setRebindSession(async current => { subscribe(current); await bind(current); });
	await bind(session);
	if (options.afterListener) renderer.addInputListener(() => { record("other_input_listener"); });
	if (options.shortcut) editor.onExtensionShortcut = data => bindings.matches(data, "app.interrupt");
	if (options.autocomplete) {
		editor.setAutocompleteProvider({ triggerCharacters: ["/"], getSuggestions: async () => ({ items: [{ value: "/help", label: "/help" }], prefix: "/" }),
			applyCompletion: () => ({ lines: ["/help"], cursorLine: 0, cursorCol: 5 }) });
		editor.setText("/"); terminal.input("\t"); await until(() => editor.isShowingAutocomplete(), "autocomplete");
	}
	if (options.inactive) {
		assert(!session.getActiveToolNames().includes("compact_session"), "mode/tool selection must not be overridden");
		assert.equal(mode.extensionTerminalInputSubscriptions.size, options.mode && options.mode !== "tui" ? 0 : 1);
		if (options.reloadInactive) {
			await session.reload();
			assert(!session.getActiveToolNames().includes("compact_session"), "reload must preserve mode/exclusions");
		}
	} else if (options.manualOnly) {
		await session.compact(focus);
		assert.equal(activity.length, 0, "unowned manual compaction is left entirely to Pi");
		assert.equal(session.sessionManager.getEntries().filter(entry => entry.type === "compaction").length, 1);
		assert(!session.sessionManager.getEntries().some(entry => entry.type === "custom_message"));
	} else {
		assert(session.getActiveToolNames().includes("compact_session"));
		await originalSession.prompt("Begin the approved slice.");
		await until(() => originalSession.isIdle && (!active || options.disposeDirect), "original transition idle");
		await Promise.all(flushes);
		if (replacing) await replacing;
		await until(() => session.isIdle, "current session idle");
		await sleep(options.delayedInput ? 40 : 5);
		const entries = originalSession.sessionManager.getEntries();
		const saved = entries.filter(entry => entry.type === "compaction");
		const custom = entries.filter(entry => entry.type === "custom_message" && entry.customType === "workcell.compaction.resume");
		pairs(entries); assert.deepEqual(errors, []);
		const interrupted = options.stage && !options.consumeFirst && !options.nonInterrupt && options.stage !== "resumed";
		const rejected = options.badPrompt || options.mixed || options.duplicate || options.changedResult;
		const failed = options.small || options.providerFailure || options.hookCancel || options.abortApi;
		const suppressed = interrupted || rejected || failed || options.replace || options.branchChange || options.disposeDirect;
		assert.equal(custom.length, suppressed ? 0 : options.successive ? 2 : 1, "exactly one resume per successful native transition");
		if (interrupted || failed || options.replace || options.disposeDirect) {
			assert.equal(saved.length, ["persisted", "handoff"].includes(options.stage) || options.replace === "tree" ? 1 : 0);
		}
		if (!suppressed) {
			assert.equal(session.sessionId, originalId);
			assert.deepEqual(custom.map(entry => contentText(entry.content)), options.successive ? [resumePrompt, nextPrompt] : [resumePrompt]);
			if (options.stage === "resumed") {
				assert(entries.some(entry => entry.type === "message" && entry.message.role === "assistant" && entry.message.stopReason === "aborted"));
			} else assert.equal(session.getLastAssistantText(), FINAL);
			if (options.loop) assert(entries.some(entry => entry.type === "message" && entry.message.role === "toolResult" && entry.message.isError && contentText(entry.message.content).includes("immediately")));
			assert.equal(saved.length, custom.length);
			for (const entry of saved) { assert(entry.usage); assert(entry.tokensBefore > 400); assert.equal(entry.fromHook === true, !!options.hookSummary); }
			assert(seededIds.every(id => originalSession.sessionManager.getEntry(id)), "native raw history retained");
			pairs(session.sessionManager.buildSessionProjection().messages.map(message => ({ type: "message", message })));
			assert.equal(session.getSessionStats().tokens.total, replies.reduce((sum, message) => sum + message.usage.totalTokens, options.hookSummary ? usage(55).totalTokens : 0), "all native summary/agent usage accounted");
			assert(Math.abs(session.getSessionStats().cost - replies.reduce((sum, message) => sum + message.usage.cost.total, options.hookSummary ? usage(55).cost.total : 0)) < 1e-10);
			if (!options.hookSummary && preparations.some(preparation => preparation.isSplitTurn && preparation.messagesToSummarize.length)) {
				const summaries = trace.filter(event => event.type === "provider_request" && event.isSummary);
				assert(summaries.some(event => event.text.includes(`Additional focus: ${focus}`)));
				assert(summaries.some(event => !event.text.includes(`Additional focus: ${focus}`)), "native split prefix remains unmodified");
			}
		}
		if (options.queueInput || options.preExisting) {
			const dispatch = trace.find(event => event.type === "activity" && event.outcome === "resumed");
			for (const item of queueItems) {
				assert.equal(entries.filter(entry => entry.type === "message" && entry.message.role === "user" && contentText(entry.message.content) === item.text).length, 1);
				const received = trace.filter(event => event.type === "provider_request" && !event.isSummary && event.text.includes(item.text));
				assert(received.length > 0, "queued text reaches model");
				assert(received.every(event => event.index > dispatch.index), "queued text is consumed after resume dispatch");
			}
			assert.equal(mode.compactionQueuedMessages.length, 0); assert.equal(session.pendingMessageCount, 0);
			assert(trace.filter(event => event.type === "provider_request" && !event.isSummary)[1].text.includes(resumePrompt));
			if (options.slowResume && options.items) for (const item of queueItems.slice(1)) {
				assert(trace.some(event => event.type === "queue_update" && event[item.mode === "followUp" ? "followUp" : "steering"].includes(item.text)));
			}
		}
		if (options.queueRestore) { assert(editor.getText().includes("QUEUE_TO_RESTORE")); assert.equal(mode.compactionQueuedMessages.length, 0); }
		if (options.autocomplete) assert.equal(editor.isShowingAutocomplete(), false);
		if (!options.queueInput && !options.preExisting && !options.replace && !options.branchChange && !options.disposeDirect) {
			assert.equal(notifications, options.notifications === false || options.isTTY === false ? 0 : 1, "one final/terminal ready, never intermediate");
		}
		assert(!trace.some(event => event.type === "ready" && event.active), "no readiness during compaction/resume gap");
		if (options.replace && !["tree", "reload", "shutdown"].includes(options.replace)) assert.notEqual(session.sessionId, originalId);
		if (options.replace === "tree") assert.equal(session.sessionManager.getLeafId(), seededIds[1], "do not block navigation at handoff");
	}
	if (options.disposeDirect) {
		// Like a TUI host teardown, remove view-owned input listeners when disposal bypasses shutdown hooks.
		mode.clearExtensionTerminalInputListeners();
	} else await runtime.dispose();
	assert.equal(mode.extensionTerminalInputSubscriptions.size, 0, "shutdown/reload/replacement leaves no raw listeners");
	cleanupSession = undefined; renderer.stop(); cleanupRenderer = undefined;
	process.stdout.write = originalWrite;
	const report = { name, passed: true, compactions, resumes: activity.filter(state => state.outcome === "resumed").length,
		notifications, nativeInterrupts, terminalKeys, terminalOutcome, agentRequests: trace.filter(event => event.type === "provider_request" && !event.isSummary).length };
	reports.push(report);
}

const mixed = [{ text: QUEUED, mode: "steer" }, { text: "QUEUE_STEER_TWO", mode: "steer" }, { text: "QUEUE_FOLLOWUP_ONE", mode: "followUp" }];
const cases = [
	["native-success", {}], ["notification-first", { notifyFirst: true }], ["notifications-absent", { notifications: false }], ["non-tty-notifications", { isTTY: false }],
	["autonomous-successive-slices", { successive: true }], ["immediate-loop-rejected", { loop: true }],
	["tui-steering-ordinary", { queueInput: true }], ["tui-steering-synchronous", { queueInput: true, syncInput: true }],
	["tui-steering-delayed", { queueInput: true, delayedInput: true }], ["tui-followup-ordinary", { queueInput: true, queueMode: "followUp" }],
	["tui-followup-delayed", { queueInput: true, queueMode: "followUp", delayedInput: true }],
	["tui-multiple-mixed", { queueInput: true, items: mixed, slowResume: true }], ["tui-multiple-mixed-delayed", { queueInput: true, items: mixed, slowResume: true, delayedInput: true }],
	["preexisting-steering", { preExisting: true }], ["preexisting-followup", { preExisting: true, queueMode: "followUp" }], ["preexisting-mixed", { preExisting: true, items: mixed, slowResume: true }],
	["native-provider-failure", { providerFailure: true }], ["native-hook-cancel", { hookCancel: true }],
	["native-hook-summary", { hookSummary: true }], ["manual-compaction-unowned", { manualOnly: true }], ["native-api-abort", { abortApi: true }], ["native-small-session", { small: true }],
	["changed-acknowledgement", { changedResult: true }], ["standalone-mixed-rejected", { mixed: true }], ["standalone-duplicate-rejected", { duplicate: true }], ["empty-prompt-rejected", { badPrompt: true }],
	["stale-branch-callback", { branchChange: true }], ["sdk-direct-disposal", { disposeDirect: true }],
	...["accepted", "waiting-idle", "summary", "persisted", "handoff", "resumed"].map(stage => [`escape-${stage}`, { stage }]),
	["escape-native-queue-restoration", { stage: "summary", queueRestore: true }], ["escape-autocomplete", { stage: "summary", autocomplete: true }],
	["escape-editor-shortcut", { stage: "summary", shortcut: true }], ["escape-remapped", { stage: "summary", remap: true }],
	["escape-remapped-away", { stage: "summary", remap: true, key: "\x1b", nonInterrupt: true }], ["escape-kitty", { stage: "summary", key: "\x1b[27u" }],
	["escape-ordinary-data-and-release", { noise: true }], ["escape-delegating-editor", { stage: "handoff", customEditor: true }],
	["escape-listener-before", { stage: "summary", firstListener: true }], ["escape-listener-after", { stage: "summary", afterListener: true }],
	["escape-earlier-consumer-limit", { stage: "summary", firstListener: true, consumeFirst: true }],
	...["print", "json", "rpc"].map(mode => [`inactive-${mode}`, { mode, inactive: true }]),
	["excluded-tool", { inactive: true, selection: { excludeTools: ["compact_session"] } }],
	["excluded-tool-after-reload", { inactive: true, reloadInactive: true, selection: { excludeTools: ["compact_session"] } }],
	["inactive-print-after-reload", { mode: "print", inactive: true, reloadInactive: true }],
	["explicit-tools-preserved", { inactive: true, selection: { tools: ["work"] } }], ["no-tools-preserved", { inactive: true, selection: { noTools: "all" } }],
	...["new", "fork", "switch", "reload", "tree", "shutdown"].map(replace => [`runtime-${replace}`, { replace }]),
];
try {
	const selected = selectedCase ? cases.filter(([name]) => name === selectedCase) : cases;
	assert(selected.length > 0, "unknown case");
	for (const [name, options] of selected) await runCase(name, options);
	process.stdout.write(JSON.stringify({ packageVersion, passed: true, reports }) + "\n");
} catch (error) {
	process.stdout.write = originalWrite;
	console.error(JSON.stringify({ trace }, null, 2));
	console.error(error);
	process.stdout.write(JSON.stringify({ packageVersion, passed: false, error: error.stack, reports }) + "\n");
	process.exitCode = 1;
} finally {
	process.stdout.write = originalWrite;
	if (originalTTY) Object.defineProperty(process.stdout, "isTTY", originalTTY); else delete process.stdout.isTTY;
	cleanupSession?.dispose(); cleanupRenderer?.stop();
	await rm(isolated, { recursive: true, force: true });
}
