import { pathToFileURL } from "node:url";

const [extensionPath, scenarioJson] = process.argv.slice(2);
if (!extensionPath || !scenarioJson) {
	throw new Error("usage: run_pi_notification_extension.mjs <extension> <scenario-json>");
}

const scenario = JSON.parse(scenarioJson);
const handlers = new Map();
const registeredEvents = [];
const writes = [];
const originalWrite = process.stdout.write;
const originalIsTTY = Object.getOwnPropertyDescriptor(process.stdout, "isTTY");

Object.defineProperty(process.stdout, "isTTY", {
	configurable: true,
	value: scenario.isTTY,
});
process.stdout.write = (chunk, encoding) => {
	writes.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk, encoding));
	return true;
};

try {
	const { default: register } = await import(pathToFileURL(extensionPath).href);
	register({
		on(event, handler) {
			registeredEvents.push(event);
			handlers.set(event, handler);
		},
	});

	const settled = handlers.get("agent_settled");
	for (let invocation = 0; invocation < (scenario.invocations ?? 1); invocation += 1) {
		if (settled) {
			await settled(
				{ type: "agent_settled" },
				{
					mode: scenario.mode,
					isIdle: () => scenario.isIdle,
				},
			);
		}
	}
} finally {
	process.stdout.write = originalWrite;
	if (originalIsTTY) {
		Object.defineProperty(process.stdout, "isTTY", originalIsTTY);
	} else {
		delete process.stdout.isTTY;
	}
}

process.stdout.write(
	JSON.stringify({
		registeredEvents,
		writes: writes.map((write) => write.toString("base64")),
	}),
);
