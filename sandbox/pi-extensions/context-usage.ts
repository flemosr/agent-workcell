import { Type } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function contextUsage(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "get_context_usage",
		label: "Get context usage",
		description: "Return Pi's estimated active-context tokens, applicable context window, and percentage used at execution time, not cumulative session usage or the compaction threshold. Null tokens/percent mean unknown, such as after compaction before fresh valid assistant usage; all fields are null when native usage is unavailable. Uses Pi's native accounting and routed-model limits. Excludes this tool's result and later responses. Read-only; does not compact or change model, effort, or settings.",
		promptSnippet: "Inspect estimated active-context usage at call time; null values mean unknown or unavailable.",
		parameters: Type.Object({}, { additionalProperties: false }),
		outputSchema: Type.Object({
			tokens: Type.Union([Type.Number(), Type.Null()]),
			contextWindow: Type.Union([Type.Number(), Type.Null()]),
			percent: Type.Union([Type.Number(), Type.Null()]),
		}, { additionalProperties: false }),
		annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
		async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
			const usage = ctx.getContextUsage();
			const payload = {
				tokens: usage?.tokens ?? null,
				contextWindow: usage?.contextWindow ?? null,
				percent: usage?.percent ?? null,
			};
			return {
				content: [{ type: "text", text: JSON.stringify(payload) }],
				structuredContent: payload,
				details: payload,
			};
		},
	});
}
