// Real Pi services and extension loading; only provider responses are scripted.
import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [rootArgument, extensionArgument, selectedCase] = process.argv.slice(2);
if (!rootArgument || !extensionArgument || !process.execArgv.includes("--experimental-import-meta-resolve")) {
	throw new Error("usage: node --experimental-import-meta-resolve run_pi_context_usage.mjs <pi-package-root> <extension> [case]");
}
const root = resolve(rootArgument);
const extensionPath = resolve(extensionArgument);
const isolated = await mkdtemp(join(tmpdir(), "workcell-pi-context-"));
process.env.HOME = join(isolated, "home");
process.env.PI_CODING_AGENT_DIR = join(isolated, "global");
process.env.XDG_CACHE_HOME = join(isolated, "cache");
process.env.PI_OFFLINE = "1";
delete process.env.PI_SESSION_FILE;
delete process.env.PI_SESSION_ID;
globalThis.fetch = () => { throw new Error("Network forbidden in offline SDK tests"); };
const GET = "get_context_usage";
const call = (name = GET, args = {}) => ({ name, args });
const zeroCost = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 };
const usage = totalTokens => ({ input: totalTokens, output: 0, cacheRead: 0, cacheWrite: 0,
	totalTokens, cost: { ...zeroCost } });
const dispatchedUsage = { input: 333, output: 17, cacheRead: 2500, cacheWrite: 150,
	totalTokens: 3000, cost: { ...zeroCost } };
const unavailable = { tokens: null, contextWindow: null, percent: null };
const reports = [];

try {
	const sdk = await import(pathToFileURL(join(root, "dist/index.js")));
	const ai = await import(import.meta.resolve("@earendil-works/pi-ai", pathToFileURL(join(root, "package.json")).href));
	const { createAgentSession, DefaultResourceLoader, ModelRuntime, SettingsManager, SessionManager } = sdk;
	const { Type, InMemoryCredentialStore, createAssistantMessageEventStream, contentText, validateToolArguments } = ai;
	const packageVersion = JSON.parse(await readFile(join(root, "package.json"), "utf8")).version;

	async function runCase(name, options, verify) {
		if (selectedCase && selectedCase !== name) return;
		const cwd = join(isolated, name);
		const agentDir = join(cwd, "agent");
		await mkdir(agentDir, { recursive: true });
		const settingsManager = SettingsManager.inMemory({ defaultTools: options.defaultTools ?? [],
			compaction: { enabled: false }, retry: { enabled: false } });
		const settingsBefore = structuredClone(settingsManager.getSettings());
		const modelRuntime = await ModelRuntime.create({ credentials: new InMemoryCredentialStore(), modelsPath: null,
			modelsStorePath: join(cwd, "models-cache.json"), refreshOnCreate: false, allowModelNetwork: false });
		const script = options.script ?? [[call()]];
		const requests = [];
		const results = [];
		const snapshots = new Map();
		const resultStates = new Map();
		const errors = [];
		let session;
		let boundContext;
		function streamSimple(model, _context, streamOptions) {
			const index = requests.length;
			requests.push({ model: model.id, provider: model.provider, effort: streamOptions.reasoning ?? "off" });
			const step = script[index];
			const message = { role: "assistant", api: model.api, provider: model.provider, model: model.id,
				content: step ? step.map(({ name: toolName, args }, i) => ({ type: "toolCall", id: `call-${index}-${i}`, name: toolName, arguments: args }))
					: [{ type: "text", text: "Offline complete" }],
				stopReason: step ? "toolUse" : "stop", usage: structuredClone(dispatchedUsage), timestamp: Date.now() };
			const stream = createAssistantMessageEventStream();
			stream.push({ type: "start", partial: { ...message, stopReason: "pending" } });
			stream.push({ type: "done", reason: message.stopReason, message });
			stream.end();
			return stream;
		}
		modelRuntime.registerProvider("workcell-offline-context", { api: "workcell-offline-context", apiKey: "offline-only",
			baseUrl: "https://offline.invalid", streamSimple,
			models: [{ id: "physical", name: "Offline context", reasoning: false, input: ["text"],
				contextWindow: options.contextWindow ?? 32000, maxTokens: 1000, cost: { ...zeroCost } }] });
		const physicalModel = modelRuntime.getModel("workcell-offline-context", "physical");
		if (options.virtual) modelRuntime.registerVirtualModel({ provider: "workcell-offline-context", id: "router",
			name: "Offline router", contextWindow: 64000, route: () => ({ model: physicalModel, thinkingLevel: "off" }) });
		const model = options.virtual ? modelRuntime.getModel("workcell-offline-context", "router") : physicalModel;
		const identity = { provider: model.provider, id: model.id };
		const manager = SessionManager.inMemory(cwd);
		function controlState() {
			return structuredClone({ model: { provider: session.model.provider, id: session.model.id },
				effort: session.thinkingLevel, settings: settingsManager.getSettings(), leafId: manager.getLeafId(),
				entries: manager.getEntries().filter(entry => entry.type !== "message") });
		}
		function observer(pi) {
			pi.on("session_start", (_event, ctx) => { boundContext = ctx; });
			pi.on("tool_call", (event, ctx) => {
				if (event.toolName === GET) snapshots.set(event.toolCallId, {
					payload: ctx.getContextUsage() ?? unavailable, state: controlState(),
				});
			});
			if (options.nested) pi.registerTool({ name: "nested_usage", label: "Nested SDK check",
				description: "Offline nested context getter check", parameters: Type.Object({}),
				async execute(_id, _args, _signal, _update, ctx) {
					assert(ctx.tools.some(tool => tool.name === GET), "active getter is callable programmatically");
					return ctx.executeTool(GET, {});
				} });
		}
		const resourceLoader = new DefaultResourceLoader({ cwd, agentDir, settingsManager, additionalExtensionPaths: [extensionPath],
			noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
			systemPrompt: "Offline SDK test; only scripted tools.", extensionFactories: [observer] });
		await resourceLoader.reload();
		assert.deepEqual(resourceLoader.getExtensions().errors, []);
		const shipped = resourceLoader.getExtensions().extensions.find(extension => extension.path === extensionPath);
		assert(shipped, "explicit image-owned extension loads with discovery disabled");
		const getter = shipped.tools.get(GET).definition;
		assert.deepEqual(Object.keys(getter.parameters.properties), []);
		assert.equal(getter.parameters.additionalProperties, false);
		assert.deepEqual(getter.outputSchema.required, ["tokens", "contextWindow", "percent"]);
		assert.equal(getter.outputSchema.additionalProperties, false);
		assert.equal(getter.exposure ?? "direct", "direct");
		assert.deepEqual(getter.annotations, { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false });
		function checkPayload(result, expected) {
			assert.deepEqual(result.structuredContent, expected);
			assert.deepEqual(result.details, expected);
			assert.deepEqual(result.content, [{ type: "text", text: JSON.stringify(expected) }]);
			validateToolArguments({ name: GET, parameters: getter.outputSchema }, { name: GET, arguments: result.structuredContent });
			assert.equal(result.usage, undefined, "getter makes no nested model requests");
			assert.notEqual(result.terminate, true, "getter does not change the normal continuation scheduler");
		}
		try {
			({ session } = await createAgentSession({ cwd, agentDir, modelRuntime, model, settingsManager, resourceLoader,
				sessionManager: manager, thinkingLevel: "off", ...options.selection }));
			session.subscribe(event => {
				if (event.type !== "tool_execution_end") return;
				results.push(event);
				if (event.toolName !== GET || event.isError) return;
				resultStates.set(event.toolCallId, controlState());
			});
			await session.bindExtensions({ mode: options.mode ?? "print", onError: error => errors.push(error) });
			assert(boundContext, "direct snapshot checks use a genuine bound extension context");
			let directCalls = 0;
			async function directSnapshot() {
				// Cold/unknown states cannot always be reached by a model-issued tool call:
				// the issuing assistant may already provide fresh usage. No API stubs here.
				const expected = boundContext.getContextUsage() ?? unavailable;
				const before = controlState();
				const requestCount = requests.length;
				const result = await getter.execute(`direct-${directCalls++}`, {}, undefined, undefined, boundContext);
				checkPayload(result, expected);
				assert.deepEqual(controlState(), before);
				assert.equal(requests.length, requestCount);
				return result.structuredContent;
			}
			const appendUser = text => manager.appendMessage({ role: "user", content: text, timestamp: Date.now() });
			const appendAssistant = tokens => manager.appendMessage({ role: "assistant", api: physicalModel.api,
				provider: physicalModel.provider, model: physicalModel.id, content: [{ type: "text", text: "Seeded history" }],
				usage: usage(tokens), stopReason: "stop", timestamp: Date.now() });
			const successfulResults = () => results.filter(event => event.toolName === GET && !event.isError);
			await verify({ session, manager, requests, results, script, appendUser, appendAssistant, directSnapshot, successfulResults });
			for (const event of successfulResults()) {
				const snapshot = snapshots.get(event.toolCallId);
				assert(snapshot, "native snapshot was captured at the getter's tool-call boundary");
				checkPayload(event.result, snapshot.payload);
				assert.deepEqual(resultStates.get(event.toolCallId), snapshot.state, "getter does not mutate session controls or settings");
			}
			assert.deepEqual({ provider: session.model.provider, id: session.model.id }, identity);
			assert(requests.every(request => request.model === physicalModel.id && request.provider === physicalModel.provider && request.effort === "off"));
			assert.deepEqual(settingsManager.getSettings(), settingsBefore);
			assert.deepEqual(errors, []);
			assert.deepEqual(resourceLoader.getExtensions().errors, []);
			reports.push({ name, passed: true });
		} finally { session?.dispose(); }
	}

	await runCase("roundtrip", {}, async test => {
		test.appendUser("Historical usage is not the current context size.");
		test.appendAssistant(12000);
		test.manager.appendUsage("offline-non-context", "workcell-offline-context", "physical", usage(90000));
		await test.session.prompt("Inspect context once.");
		assert.equal(test.successfulResults().length, 1);
		assert.deepEqual(test.successfulResults()[0].result.structuredContent, { tokens: 3000, contextWindow: 32000, percent: 9.375 });
		assert.equal(test.requests.length, 2, "only the issuing response and normal follow-up are requested");
	});

	await runCase("empty-zero", {}, async test => {
		assert.deepEqual(await test.directSnapshot(), { tokens: 0, contextWindow: 32000, percent: 0 });
		assert.equal(test.requests.length, 0);
	});

	await runCase("heuristic-trailing", {}, async test => {
		test.appendUser("Unmeasured history ".repeat(100));
		assert((await test.directSnapshot()).tokens > 0, "native heuristic estimates unmeasured history");
		test.appendAssistant(4000);
		test.appendUser("Additional context ".repeat(100));
		assert((await test.directSnapshot()).tokens > 4000, "native accounting includes trailing context");
		assert.equal(test.requests.length, 0);
	});

	await runCase("post-compaction", {}, async test => {
		const first = test.appendUser("Kept history");
		test.appendAssistant(12000);
		test.manager.appendCompaction("Offline fixture summary", first, 12000);
		assert.deepEqual(await test.directSnapshot(), { tokens: null, contextWindow: 32000, percent: null });
		test.appendAssistant(600);
		assert.deepEqual(await test.directSnapshot(), { tokens: 600, contextWindow: 32000, percent: 1.875 });
		assert.equal(test.requests.length, 0, "seeded compaction and snapshots make no summary/provider calls");
	});

	await runCase("unavailable-limit", { contextWindow: 0 }, async test => {
		assert.equal(test.session.getContextUsage(), undefined);
		assert.deepEqual(await test.directSnapshot(), unavailable);
		assert.equal(test.requests.length, 0);
	});

	await runCase("fractional-over-window", {}, async test => {
		test.appendUser("Recorded history");
		test.appendAssistant(601);
		const fractional = await test.directSnapshot();
		assert.equal(fractional.tokens, 601);
		assert.equal(fractional.contextWindow, 32000);
		assert(fractional.percent > 1.87 && fractional.percent < 1.89);
		assert.notEqual(fractional.percent, Number(fractional.percent.toFixed(2)), "native percentage is not rounded");
		test.appendAssistant(40000);
		assert.deepEqual(await test.directSnapshot(), { tokens: 40000, contextWindow: 32000, percent: 125 });
	});

	await runCase("active-branch", {}, async test => {
		const ancestor = test.appendUser("Common ancestor");
		const abandoned = test.appendAssistant(50000);
		test.manager.branch(ancestor);
		test.appendAssistant(777);
		assert.equal((await test.directSnapshot()).tokens, 777);
		test.manager.branch(abandoned);
		assert.equal((await test.directSnapshot()).tokens, 50000);
	});

	await runCase("virtual-selection", { virtual: true }, async test => {
		assert.equal((await test.directSnapshot()).contextWindow, 64000, "virtual declared limit applies before dispatch");
		await test.session.prompt("Inspect the native routed-model limit.");
		assert.equal(test.successfulResults().length, 1);
		assert.equal(test.successfulResults()[0].result.structuredContent.contextWindow, 32000);
		assert.equal(test.session.model.id, "router");
	});

	await runCase("invalid-inputs", { script: [[call(GET, { tokens: 1 })], [call(GET, { reason: "not accepted" })], [call()]] }, async test => {
		await test.session.prompt("Reject extra input properties.");
		const failures = test.results.filter(event => event.toolName === GET && event.isError);
		assert.equal(failures.length, 2);
		assert(failures.every(event => contentText(event.result.content).length > 0));
		assert.equal(test.successfulResults().length, 1);
	});

	await runCase("nested-access", { nested: true, script: [[call("nested_usage")]] }, async test => {
		await test.session.prompt("Inspect context through nested tool execution.");
		assert.equal(test.successfulResults().length, 1);
		assert(test.successfulResults()[0].parentToolCallId, "the getter result is a genuine nested execution event");
		assert(!test.results.some(event => event.isError));
		assert.equal(test.requests.length, 2);
	});

	for (const mode of ["tui", "print", "json", "rpc"]) await runCase(`mode-${mode}`, { mode }, async test => {
		await test.session.prompt("Inspect context without terminal UI dependencies.");
		assert.equal(test.successfulResults().length, 1);
		assert(!test.results.some(event => event.isError));
	});

	for (const [name, selection, expected] of [
		["default-availability", {}, [GET]],
		["allowlist", { tools: [GET] }, [GET]],
		["allowlist-omits", { tools: ["read"] }, ["read"]],
		["exclude-getter", { excludeTools: [GET] }, []],
		["no-tools", { noTools: "all" }, []],
		["no-builtin-tools", { noTools: "builtin" }, [GET]],
	]) await runCase(name, { selection, defaultTools: name === "no-builtin-tools" ? ["read"] : [] }, async test => {
		assert.deepEqual(test.session.getActiveToolNames().sort(), expected);
		await test.session.reload();
		assert.deepEqual(test.session.getActiveToolNames().sort(), expected, "reload must preserve tool selection");
		assert.equal(test.requests.length, 0);
	});

	assert(reports.length, `Unknown case: ${selectedCase}`);
	console.log(JSON.stringify({ passed: true, packageVersion, reports }));
} finally {
	await rm(isolated, { recursive: true, force: true });
}
