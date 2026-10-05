import { getSupportedThinkingLevels, StringEnum, Type } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"] as const;

function availableEffortLevels(ctx: ExtensionContext) {
	if (!ctx.model?.reasoning) return [];
	const supported = getSupportedThinkingLevels(ctx.model);
	return EFFORT_LEVELS.filter(level => supported.includes(level));
}

export default function reasoningEffort(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "get_model_info",
		label: "Get model info",
		description: "Return the currently selected Pi model/provider, current selected Pi effort, and effort levels accepted by set_reasoning_effort. An empty level list means no supported choices. Reports the selected model, not a virtual router's next physical model. Does not change any state.",
		promptSnippet: "Inspect the current model and available reasoning effort choices.",
		parameters: Type.Object({}, { additionalProperties: false }),
		outputSchema: Type.Object({
			model: Type.Union([
				Type.Object({ provider: Type.String(), id: Type.String() }, { additionalProperties: false }),
				Type.Null(),
			]),
			currentEffort: StringEnum(["off", "minimal", ...EFFORT_LEVELS]),
			availableEffortLevels: Type.Array(StringEnum(EFFORT_LEVELS)),
		}, { additionalProperties: false }),
		annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
		async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
			const payload = {
				model: ctx.model ? { provider: ctx.model.provider, id: ctx.model.id } : null,
				currentEffort: pi.getThinkingLevel(),
				availableEffortLevels: availableEffortLevels(ctx),
			};
			return {
				content: [{ type: "text", text: JSON.stringify(payload) }],
				structuredContent: payload,
				details: payload,
			};
		},
	});

	pi.registerTool({
		name: "set_reasoning_effort",
		label: "Set reasoning effort",
		description: "Set the selected reasoning effort for subsequent model requests in this Pi session. Use get_model_info first to discover supported choices. Takes effect on the next request, including automatic continuation after this tool call, not the response already running. Provider and virtual-router level mappings still apply. Changes neither the model/provider nor startup defaults. Unsupported levels fail without changing effort; off and minimal are not accepted.",
		promptSnippet: "Select a supported reasoning effort for subsequent model requests.",
		promptGuidelines: [
			"Use get_model_info to check available effort levels before setting one; do not set an effort when the list is empty.",
			"Change effort at meaningful work boundaries, not repeatedly without doing work. The first response uses the configured startup effort.",
		],
		exposure: "model-only",
		executionMode: "sequential",
		annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
		parameters: Type.Object({
			level: StringEnum(EFFORT_LEVELS, { description: "An availableEffortLevels value returned by get_model_info." }),
		}, { additionalProperties: false }),
		async execute(_toolCallId, params, signal, _onUpdate, ctx) {
			if (signal?.aborted) throw new Error("Reasoning effort change canceled.");
			const available = availableEffortLevels(ctx);
			if (!available.includes(params.level)) {
				throw new Error(`Unsupported reasoning effort ${JSON.stringify(params.level)}. Available levels: ${available.join(", ") || "none"}. Use get_model_info to inspect the current model.`);
			}
			const previousEffort = pi.getThinkingLevel();
			pi.setThinkingLevel(params.level);
			const currentEffort = pi.getThinkingLevel();
			return {
				content: [{ type: "text", text: `Selected reasoning effort: ${previousEffort} -> ${currentEffort}. Applies to the next model request; provider/virtual-router level mappings still apply. Model/provider and startup defaults are unchanged.` }],
				details: { previousEffort, currentEffort },
			};
		},
	});
}
