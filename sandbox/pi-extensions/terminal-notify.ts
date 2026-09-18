import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const NOTIFICATION = "\x1b]777;notify;Pi;Ready for input\x07";

export default function terminalNotify(pi: ExtensionAPI): void {
	pi.on("agent_settled", (_event, ctx) => {
		if (ctx.mode !== "tui" || process.stdout.isTTY !== true || !ctx.isIdle()) {
			return;
		}

		process.stdout.write(NOTIFICATION);
	});
}
