package com.aiops.api.api.pipeline;

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Template-based DraftDoc generator — turns a Pipeline JSON into the
 * Skill-Registry-facing document shape.
 *
 * <p>Ported from Python {@code app/services/pipeline_builder/doc_generator.py}.
 * Pure function: no I/O, no LLM. The output shape matches the planned LLM
 * variant so the Frontend Review Modal sees a stable contract regardless of
 * generator mode.
 */
@Component
public class PipelineDocGenerator {

	public Map<String, Object> generate(
			long pipelineId,
			String pipelineName,
			String pipelineVersion,
			String pipelineKind,
			String description,
			Map<String, Object> pipelineJson) {

		List<Map<String, Object>> nodes = asListOfMaps(pipelineJson.get("nodes"));
		List<Map<String, Object>> declaredInputs = asListOfMaps(pipelineJson.get("inputs"));

		boolean hasAlert = nodes.stream().anyMatch(n -> "block_alert".equals(n.get("block_id")));
		boolean hasChart = nodes.stream().anyMatch(n -> "block_chart".equals(n.get("block_id")));

		// use_case — fall back to description; if empty, synthesize from node chain.
		String useCase = description == null ? "" : description.strip();
		if (useCase.isEmpty()) {
			useCase = summarizeNodes(nodes)
					+ " — 使用者可用於" + (hasAlert ? "巡檢並告警" : "查詢並視覺化")
					+ "（" + pipelineKind + "）。";
		}

		// when_to_use — one-liner per logic node.
		List<String> whenToUse = new ArrayList<>();
		for (Map<String, Object> n : nodes) {
			String bid = String.valueOf(n.getOrDefault("block_id", ""));
			Map<String, Object> params = asMap(n.get("params"));
			switch (bid) {
				case "block_threshold" -> {
					String col = String.valueOf(params.getOrDefault("column", "?"));
					Object op = params.get("operator");
					Object boundType = params.get("bound_type");
					if (op != null) {
						whenToUse.add("需偵測 " + col + " " + op + " " + params.get("target") + " 的情境");
					} else if (boundType != null) {
						whenToUse.add("需偵測 " + col + " 超出 " + boundType + " bound 的情境");
					}
				}
				case "block_consecutive_rule" -> whenToUse.add(
						"需偵測 " + params.getOrDefault("flag_column", "?")
								+ " 最近 " + params.getOrDefault("count", "?") + " 次連續觸發");
				case "block_weco_rules" -> {
					List<?> rules = params.get("rules") instanceof List<?> r ? r
							: List.of("R1", "R2", "R5", "R6");
					whenToUse.add("套用 SPC WECO rules（" + String.join(",", rules.stream().map(String::valueOf).toList()) + "）偵測異常 pattern");
				}
				default -> { /* not a logic node we summarise */ }
			}
		}
		if (whenToUse.isEmpty()) {
			whenToUse.add("無明確條件邏輯 — 建議補充 use_case + 觸發情境（手動編輯 description 重新產生）");
		}

		// inputs_schema — derived from declared inputs.
		List<Map<String, Object>> inputsSchema = new ArrayList<>();
		for (Map<String, Object> inp : declaredInputs) {
			Map<String, Object> entry = new LinkedHashMap<>();
			entry.put("name", inp.get("name"));
			entry.put("type", inp.getOrDefault("type", "string"));
			entry.put("required", Boolean.TRUE.equals(inp.get("required")));
			Object descRaw = inp.get("description");
			String desc = (descRaw instanceof String s && !s.isBlank())
					? s : "Pipeline input '" + inp.get("name") + "'";
			entry.put("description", desc);
			entry.put("example", inp.get("example"));
			inputsSchema.add(entry);
		}

		// outputs_schema — templated by kind + chart presence.
		Map<String, Object> outputsSchema = new LinkedHashMap<>();
		outputsSchema.put("triggered_meaning",
				"True 表示 pipeline 的 terminal logic node 認定有異常 / 條件成立");
		outputsSchema.put("evidence_schema",
				"DataFrame — 全部被評估的 rows + `triggered_row` bool column；"
						+ "額外欄位隨 logic 類型不同（threshold: violation_side/violated_bound；"
						+ "weco: triggered_rules/violation_side；consecutive: trigger_id/run_position 等）");
		outputsSchema.put("chart_summary", hasChart
				? "Pipeline Results 面板會按 sequence 順序顯示各 chart_spec"
				: null);

		// example_invocation: example/default values from declared inputs.
		Map<String, Object> exampleValues = new LinkedHashMap<>();
		for (Map<String, Object> inp : declaredInputs) {
			Object name = inp.get("name");
			if (name == null) continue;
			Object example = inp.get("example");
			Object def = inp.get("default");
			if (example != null) {
				exampleValues.put(String.valueOf(name), example);
			} else if (def != null) {
				exampleValues.put(String.valueOf(name), def);
			}
		}
		Map<String, Object> exampleInvocation = new LinkedHashMap<>();
		exampleInvocation.put("inputs", exampleValues.isEmpty()
				? Map.of("# hint", "no declared inputs on this pipeline")
				: exampleValues);

		// tags — kind + detected block patterns.
		List<String> tags = new ArrayList<>();
		tags.add(pipelineKind);
		if (nodes.stream().anyMatch(n -> "block_process_history".equals(n.get("block_id")))) tags.add("spc");
		if (nodes.stream().anyMatch(n -> "block_weco_rules".equals(n.get("block_id")))) tags.add("weco");
		if (nodes.stream().anyMatch(n -> "block_cpk".equals(n.get("block_id")))) tags.add("capability");
		if (nodes.stream().anyMatch(n -> "block_correlation".equals(n.get("block_id")))) tags.add("correlation");

		String slug = slugify(pipelineName) + "-v" + pipelineVersion + "-p" + pipelineId;

		Map<String, Object> doc = new LinkedHashMap<>();
		doc.put("slug", slug);
		doc.put("name", pipelineName);
		doc.put("use_case", useCase);
		doc.put("when_to_use", whenToUse);
		doc.put("inputs_schema", inputsSchema);
		doc.put("outputs_schema", outputsSchema);
		doc.put("example_invocation", exampleInvocation);
		doc.put("tags", tags);
		return doc;
	}

	/** Lowercase, spaces→hyphens, strip non-alphanumeric. Stable across time. */
	static String slugify(String text) {
		if (text == null) return "pipeline";
		String cleaned = text.replaceAll("[^a-zA-Z0-9\\s\\-_]", "").trim().toLowerCase();
		cleaned = cleaned.replaceAll("[\\s_]+", "-");
		cleaned = cleaned.replaceAll("-+", "-");
		cleaned = cleaned.replaceAll("^-+|-+$", "");
		if (cleaned.length() > 60) cleaned = cleaned.substring(0, 60);
		return cleaned.isEmpty() ? "pipeline" : cleaned;
	}

	static String summarizeNodes(List<Map<String, Object>> nodes) {
		if (nodes.isEmpty()) return "（空）";
		List<String> parts = new ArrayList<>();
		for (int i = 0; i < Math.min(8, nodes.size()); i++) {
			Map<String, Object> n = nodes.get(i);
			Object label = n.get("display_label");
			if (!(label instanceof String s) || s.isBlank()) {
				label = n.getOrDefault("block_id", "?");
			}
			parts.add(String.valueOf(label));
		}
		String tail = nodes.size() <= 8 ? "" : " +" + (nodes.size() - 8) + " more";
		return String.join(" → ", parts) + tail;
	}

	@SuppressWarnings("unchecked")
	private static List<Map<String, Object>> asListOfMaps(Object o) {
		if (!(o instanceof List<?> list)) return List.of();
		List<Map<String, Object>> out = new ArrayList<>();
		for (Object item : list) {
			if (item instanceof Map<?, ?> m) out.add((Map<String, Object>) m);
		}
		return out;
	}

	@SuppressWarnings("unchecked")
	private static Map<String, Object> asMap(Object o) {
		return (o instanceof Map<?, ?> m) ? (Map<String, Object>) m : Map.of();
	}
}
