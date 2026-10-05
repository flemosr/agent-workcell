// Real Pi services and extension loading; only the provider response boundary is scripted.
import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [rootArgument, extensionArgument, selectedCase] = process.argv.slice(2);
if (!extensionArgument || !process.execArgv.includes("--experimental-import-meta-resolve")) {
	throw new Error("usage: node --experimental-import-meta-resolve run_pi_reasoning_effort.mjs <pi-package-root> <extension> [case]");
}
const root = resolve(rootArgument);
const extensionPath = resolve(extensionArgument);
const isolated = await mkdtemp(join(tmpdir(), "workcell-pi-effort-"));
process.env.HOME = join(isolated, "home");
process.env.PI_CODING_AGENT_DIR = join(isolated, "global");
process.env.XDG_CACHE_HOME = join(isolated, "cache");
delete process.env.PI_SESSION_FILE;
delete process.env.PI_SESSION_ID;
globalThis.fetch = () => { throw new Error("Network forbidden in offline SDK tests"); };
const GET = "get_model_info";
const SET = "set_reasoning_effort";
const LEVELS = ["low", "medium", "high", "xhigh", "max"];
const call = (name, args = {}) => ({ name, args });
const usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
	cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
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
		const settingsManager = SettingsManager.inMemory({ defaultThinkingLevel: "medium", defaultTools: [],
			compaction: { enabled: false }, retry: { enabled: false } });
		const settingsBefore = structuredClone(settingsManager.getSettings());
		const modelRuntime = await ModelRuntime.create({ credentials: new InMemoryCredentialStore(), modelsPath: null,
			modelsStorePath: join(cwd, "models-cache.json"), refreshOnCreate: false, allowModelNetwork: false });
		const target = modelRuntime.getModel("openai-codex", "gpt-6.1-sol");
		assert(target, "Installed Pi catalog must include the target model");
		const script = options.script ?? [];
		const requests = [];
		const results = [];
		const completed = [];
		const errors = [];
		function streamSimple(model, _context, streamOptions) {
			const index = requests.length;
			requests.push({ model: model.id, provider: model.provider, effort: streamOptions.reasoning ?? "off" });
			const step = script[index];
			const message = { role: "assistant", api: model.api, provider: model.provider, model: model.id,
				content: step ? step.map(({ name: toolName, args }, i) => ({ type: "toolCall", id: `call-${index}-${i}`, name: toolName, arguments: args }))
					: [{ type: "text", text: "Offline complete" }],
				stopReason: step ? "toolUse" : "stop", usage, timestamp: Date.now() };
			const stream = createAssistantMessageEventStream();
			stream.push({ type: "start", partial: { ...message, stopReason: "pending" } });
			stream.push({ type: "done", reason: message.stopReason, message });
			stream.end();
			return stream;
		}
		// Catalog-derived capabilities, but a different provider/id: no GPT-only implementation gate.
		modelRuntime.registerProvider("workcell-offline-effort", { api: "workcell-offline-effort", apiKey: "offline-only",
			baseUrl: "https://offline.invalid", streamSimple,
			models: [{ id: "catalog-derived", name: "Offline effort", reasoning: options.reasoning ?? true,
				thinkingLevelMap: options.map ?? target.thinkingLevelMap, input: ["text"], contextWindow: 32000, maxTokens: 1000,
				cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }] });
		const physicalModel = modelRuntime.getModel("workcell-offline-effort", "catalog-derived");
		if (options.virtual) modelRuntime.registerVirtualModel({ provider: "workcell-offline-effort", id: "router", name: "Offline router",
			thinkingLevels: ["low", "high"], route: () => ({ model: physicalModel, thinkingLevel: "medium" }) });
		const model = options.virtual ? modelRuntime.getModel("workcell-offline-effort", "router") : physicalModel;
		const identity = { provider: model.provider, id: model.id };
		function observer(pi) {
			if (options.cancel) pi.on("tool_call", (event, ctx) => { if (event.toolName === SET) ctx.abort(); });
			if (options.nested) pi.registerTool({ name: "nested_info", label: "Nested SDK check", description: "Offline nested getter check",
				parameters: Type.Object({}), async execute(_id, _args, _signal, _update, ctx) {
					assert(ctx.tools.some(tool => tool.name === GET), "getter is callable programmatically");
					assert(!ctx.tools.some(tool => tool.name === SET), "model-only setter cannot be called programmatically");
					return ctx.executeTool(GET, {});
				} });
		}
		const resourceLoader = new DefaultResourceLoader({ cwd, agentDir, settingsManager, additionalExtensionPaths: [extensionPath],
			noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
			systemPrompt: "Offline SDK test; only scripted tools.", extensionFactories: [observer] });
		await resourceLoader.reload();
		assert.deepEqual(resourceLoader.getExtensions().errors, []);
		const shipped = resourceLoader.getExtensions().extensions.find(extension => extension.path === extensionPath);
		const getter = shipped.tools.get(GET).definition;
		const setter = shipped.tools.get(SET).definition;
		assert.deepEqual(Object.keys(getter.parameters.properties), []);
		assert.deepEqual(Object.keys(setter.parameters.properties), ["level"]);
		assert.equal(getter.annotations.readOnlyHint, true);
		assert.equal(setter.exposure, "model-only");
		assert.equal(setter.executionMode, "sequential");
		const common = { cwd, agentDir, modelRuntime, model, settingsManager, resourceLoader, ...options.selection };
		let session;
		async function bind(created) {
			session = created.session;
			session.subscribe(event => {
				if (event.type === "tool_execution_end") results.push(event);
				if (event.type === "message_end" && event.message.role === "assistant") completed.push(event.message);
			});
			await session.bindExtensions({ mode: options.mode ?? "print", onError: error => errors.push(error) });
		}
		try {
			const manager = SessionManager.create(cwd, join(cwd, "sessions"));
			await bind(await createAgentSession({ ...common, sessionManager: manager, thinkingLevel: options.initial ?? "xhigh" }));
			const changes = () => session.sessionManager.getEntries().filter(entry => entry.type === "thinking_level_change");
			const initialChanges = changes().length;
			const initialEffort = session.thinkingLevel;
			const toolResults = () => session.messages.filter(message => message.role === "toolResult");
			const infoResults = () => toolResults().filter(message => message.toolName === GET).map(message => {
				assert(!message.isError, contentText(message.content));
				return JSON.parse(contentText(message.content));
			});
			const expectedInfo = (effort, levels = LEVELS) => ({ model: identity, currentEffort: effort, availableEffortLevels: levels });
			await verify({ get session() { return session; }, requests, results, completed, script, changes, initialChanges, initialEffort,
				toolResults, infoResults, expectedInfo, async reopen() {
					const file = session.sessionFile;
					assert(file, "real session file was persisted");
					session.dispose();
					await resourceLoader.reload(); // Reopening needs fresh extension factories, not disposed runtime closures.
					await bind(await createAgentSession({ ...common, sessionManager: SessionManager.open(file) }));
				} });
			for (const event of results.filter(event => event.toolName === GET && !event.isError)) {
				assert.deepEqual(event.result.structuredContent, event.result.details);
				assert.deepEqual(JSON.parse(contentText(event.result.content)), event.result.structuredContent);
				validateToolArguments({ name: GET, parameters: getter.outputSchema }, { name: GET, arguments: event.result.structuredContent });
			}
			assert.deepEqual({ provider: session.model.provider, id: session.model.id }, identity);
			assert(requests.every(request => request.model === physicalModel.id && request.provider === physicalModel.provider));
			assert.deepEqual(settingsManager.getSettings(), settingsBefore, "startup defaults/settings stay unchanged");
			assert.deepEqual(errors, []);
			reports.push({ name, passed: true });
		} finally { session?.dispose(); }
	}

	await runCase("roundtrip", { nested: true, script: [
		[call(GET)], ...LEVELS.flatMap(level => [[call(SET, { level })], [call(GET)]]),
		[call(SET, { level: "max" })], [call("nested_info")],
	] }, async test => {
		await test.session.prompt("Inspect and exercise every advertised effort level.");
		assert.deepEqual(test.infoResults(), [test.expectedInfo("xhigh"), ...LEVELS.map(level => test.expectedInfo(level))]);
		assert.deepEqual(test.requests.map(request => request.effort),
			["xhigh", "xhigh", "low", "low", "medium", "medium", "high", "high", "xhigh", "xhigh", "max", "max", "max", "max"]);
		assert.equal(test.completed[0].thinkingLevel, "xhigh", "the issuing response keeps its original effort");
		assert.deepEqual(test.changes().slice(test.initialChanges).map(entry => entry.thinkingLevel), LEVELS, "no-op adds no entry");
		const setters = test.toolResults().filter(message => message.toolName === SET);
		assert.deepEqual(setters.map(message => message.details), LEVELS.map((level, i) => ({
			previousEffort: i ? LEVELS[i - 1] : "xhigh", currentEffort: level,
		})).concat({ previousEffort: "max", currentEffort: "max" }));
		assert(setters.every(message => !message.isError && contentText(message.content).includes("next model request")));
		assert(test.results.some(event => event.parentToolCallId && event.toolName === GET));
		test.script.push(undefined, [call(GET)]); // The first undefined is the already-consumed final response.
		await test.reopen();
		assert.equal(test.session.thinkingLevel, "max", "resume restores native session effort, not startup default");
		await test.session.prompt("Inspect resumed effort.");
		assert.deepEqual(test.infoResults().at(-1), test.expectedInfo("max"));
	});

	await runCase("filtered-levels", { initial: "high",
		map: { off: null, minimal: null, low: null, medium: "medium", high: "high", xhigh: null, max: null },
		script: [[call(GET)], [call(SET, { level: "low" })], [call(SET, { level: "xhigh" })], [call(SET, { level: "medium" })], [call(GET)]] }, async test => {
		await test.session.prompt("Check restricted model capabilities.");
		assert.deepEqual(test.infoResults(), [test.expectedInfo("high", ["medium", "high"]), test.expectedInfo("medium", ["medium", "high"])]);
		const failures = test.toolResults().filter(message => message.isError);
		assert.equal(failures.length, 2);
		assert(failures.every(message => contentText(message.content).includes("Available levels: medium, high")));
		assert.deepEqual(test.requests.map(request => request.effort), ["high", "high", "high", "high", "medium", "medium"]);
		assert.deepEqual(test.changes().slice(test.initialChanges).map(entry => entry.thinkingLevel), ["medium"]);
	});

	await runCase("non-reasoning", { reasoning: false, script: [[call(GET)], [call(SET, { level: "high" })], [call(GET)]] }, async test => {
		await test.session.prompt("Inspect a model with no reasoning choices.");
		assert.deepEqual(test.infoResults(), [test.expectedInfo("off", []), test.expectedInfo("off", [])]);
		const failure = test.toolResults().find(message => message.toolName === SET);
		assert(failure.isError && contentText(failure.content).includes("Available levels: none"));
		assert(test.requests.every(request => request.effort === "off"));
		assert.equal(test.changes().length, test.initialChanges);
	});

	const invalidArgs = [{ level: "off" }, { level: "minimal" }, { level: "invalid" }, { level: null }, {},
		{ level: "low", reason: "not accepted" }, { level: "low", model: "other" }];
	await runCase("invalid-inputs", { script: [[call(GET)], ...invalidArgs.map(args => [call(SET, args)]), [call(GET)]] }, async test => {
		await test.session.prompt("Reject invalid inputs without mutations.");
		assert.equal(test.toolResults().filter(message => message.isError).length, invalidArgs.length);
		assert.deepEqual(test.infoResults(), [test.expectedInfo("xhigh"), test.expectedInfo("xhigh")]);
		assert.equal(test.changes().length, test.initialChanges);
		assert(test.requests.every(request => request.effort === "xhigh"));
	});

	await runCase("canceled", { cancel: true, script: [[call(SET, { level: "low" })]] }, async test => {
		await test.session.prompt("Cancel before mutation.");
		assert.equal(test.session.thinkingLevel, test.initialEffort);
		assert.equal(test.changes().length, test.initialChanges);
		assert.equal(test.requests.length, 1, "cancellation does not continue model work");
	});

	await runCase("native-alias-state", { initial: "minimal", script: [[call(GET)]] }, async test => {
		await test.session.prompt("Inspect a native alias without advertising duplicate setter choices.");
		assert.deepEqual(test.infoResults(), [test.expectedInfo("minimal")]);
		assert.equal(test.changes().length, test.initialChanges);
	});

	await runCase("sequential-batch", { script: [[call(SET, { level: "low" }), call(SET, { level: "high" })], [call(GET)]] }, async test => {
		await test.session.prompt("Apply batched setters in call order.");
		assert.deepEqual(test.changes().slice(test.initialChanges).map(entry => entry.thinkingLevel), ["low", "high"]);
		assert.deepEqual(test.infoResults(), [test.expectedInfo("high")]);
		assert.deepEqual(test.requests.map(request => request.effort), ["xhigh", "high", "high"]);
	});

	await runCase("virtual-selection", { virtual: true, initial: "high", script: [[call(GET)], [call(SET, { level: "low" })], [call(GET)]] }, async test => {
		await test.session.prompt("Inspect the selected virtual pair, not its physical dispatch.");
		assert.deepEqual(test.infoResults(), [test.expectedInfo("high", ["low", "high"]), test.expectedInfo("low", ["low", "high"])]);
		assert.equal(test.session.thinkingLevel, "low");
		assert(test.requests.every(request => request.effort === "medium"), "the real virtual router retains ownership of physical effort");
		assert(!test.toolResults().some(message => message.isError));
	});

	for (const mode of ["tui", "json", "rpc"]) await runCase(`mode-${mode}`, {
		mode, script: [[call(GET)], [call(SET, { level: "low" })], [call(GET)]] }, async test => {
		await test.session.prompt("Inspect and set without terminal UI dependencies.");
		assert.deepEqual(test.infoResults(), [test.expectedInfo("xhigh"), test.expectedInfo("low")]);
		assert(!test.toolResults().some(message => message.isError));
	});

	for (const [name, selection, expected] of [
		["allowlist", { tools: [GET] }, [GET]],
		["exclude-setter", { excludeTools: [SET] }, [GET]],
		["exclude-both", { excludeTools: [GET, SET] }, []],
		["no-tools", { noTools: "all" }, []],
	]) await runCase(name, { selection }, async test => {
		assert.deepEqual(test.session.getActiveToolNames().sort(), expected);
		await test.session.reload();
		assert.deepEqual(test.session.getActiveToolNames().sort(), expected, "reload must not re-enable tools");
	});

	assert(reports.length, `Unknown case: ${selectedCase}`);
	console.log(JSON.stringify({ passed: true, packageVersion, reports }));
} finally {
	await rm(isolated, { recursive: true, force: true });
}
