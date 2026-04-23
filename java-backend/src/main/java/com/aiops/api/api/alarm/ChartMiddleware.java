package com.aiops.api.api.alarm;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Component;

import java.util.*;

/**
 * Translates a Skill's {@code output_schema} + {@code findings.outputs} into
 * the ChartDSL shape the Frontend's {@code ChartListRenderer} renders.
 *
 * <p>ChartDSL (TypeScript) shape:
 * <pre>
 *   { type:"line"|"bar"|"scatter"|"boxplot"|"heatmap"|"distribution",
 *     title, data:[], x:string, y:string[],
 *     rules?:[{value,label,style}], highlight?:{field,eq} }
 * </pre>
 *
 * <p>Schema field with chart type carries the column mapping:
 *   x_key / value_key / y_keys / group_key / highlight_key / ucl_key / lcl_key.
 * We translate those into the DSL keys above.
 */
@Component
public class ChartMiddleware {

	/** Schema types that produce charts. */
	private static final Set<String> CHART_TYPES = Set.of(
			"spc_chart", "line_chart", "bar_chart", "scatter_chart", "multi_line_chart");

	private final ObjectMapper mapper;

	public ChartMiddleware(ObjectMapper mapper) {
		this.mapper = mapper;
	}

	public List<Object> buildCharts(JsonNode findings, JsonNode outputSchema) {
		if (findings == null || outputSchema == null || !outputSchema.isArray()) return List.of();
		JsonNode outputs = findings.path("outputs");
		if (outputs.isMissingNode() || !outputs.isObject()) return List.of();

		List<Object> charts = new ArrayList<>();
		for (JsonNode field : outputSchema) {
			String type = field.path("type").asText(null);
			if (type == null || !CHART_TYPES.contains(type)) continue;
			String key = field.path("key").asText(null);
			if (key == null) continue;
			JsonNode slot = outputs.get(key);
			if (slot == null || slot.isNull()) continue;

			switch (type) {
				case "spc_chart" -> charts.addAll(buildSpcCharts(field, slot));
				case "multi_line_chart" -> charts.addAll(buildMultiLineCharts(field, slot));
				default -> {
					Object c = buildSimpleChart(type, field, slot);
					if (c != null) charts.add(c);
				}
			}
		}
		return charts;
	}

	/** SPC chart: split rows by group_key (chart_type) into one sub-chart each,
	 *  with UCL/LCL rules + OOC highlight. */
	private List<Object> buildSpcCharts(JsonNode field, JsonNode slot) {
		JsonNode data = resolveDataArray(slot);
		if (data == null || data.isEmpty()) return List.of();

		String groupKey = field.path("group_key").asText("chart_type");
		String xKey = field.path("x_key").asText("eventTime");
		String valueKey = field.path("value_key").asText("value");
		String uclKey = field.path("ucl_key").asText("ucl");
		String lclKey = field.path("lcl_key").asText("lcl");
		String highlightKey = field.path("highlight_key").asText(null);
		String label = field.path("label").asText("SPC");

		// Group rows by group_key value
		Map<String, ArrayNode> groups = new LinkedHashMap<>();
		for (JsonNode row : data) {
			String g = row.path(groupKey).asText("default");
			groups.computeIfAbsent(g, k -> mapper.createArrayNode()).add(row);
		}

		List<Object> out = new ArrayList<>();
		int idx = 0;
		for (Map.Entry<String, ArrayNode> e : groups.entrySet()) {
			idx++;
			ArrayNode groupRows = e.getValue();
			ObjectNode chart = mapper.createObjectNode();
			chart.put("type", "line");
			chart.put("title", e.getKey() + " — " + label + " (" + idx + "/" + groups.size() + ")");
			chart.put("x", xKey);
			ArrayNode ys = mapper.createArrayNode();
			ys.add(valueKey);
			chart.set("y", ys);
			chart.set("data", groupRows);

			// UCL/LCL rules (from first row — SPC values are constant per group)
			if (groupRows.size() > 0) {
				ArrayNode rules = mapper.createArrayNode();
				JsonNode first = groupRows.get(0);
				if (first.has(uclKey) && first.get(uclKey).isNumber()) {
					ObjectNode ucl = mapper.createObjectNode();
					ucl.put("value", first.get(uclKey).asDouble());
					ucl.put("label", "UCL");
					ucl.put("style", "danger");
					rules.add(ucl);
				}
				if (first.has(lclKey) && first.get(lclKey).isNumber()) {
					ObjectNode lcl = mapper.createObjectNode();
					lcl.put("value", first.get(lclKey).asDouble());
					lcl.put("label", "LCL");
					lcl.put("style", "danger");
					rules.add(lcl);
				}
				if (rules.size() > 0) chart.set("rules", rules);
			}
			// Highlight: OOC points (e.g. is_ooc == true)
			if (highlightKey != null && !highlightKey.isBlank()) {
				ObjectNode hl = mapper.createObjectNode();
				hl.put("field", highlightKey);
				hl.put("eq", true);
				chart.set("highlight", hl);
			}
			out.add(chart);
		}
		return out;
	}

	/** multi_line_chart: split rows by group_key into one line per group.
	 *  Frontend expects a single chart with multiple y series (one per group),
	 *  OR (more practical given data shape) one chart per group. We emit the
	 *  latter shape — matches SPC split pattern. */
	private List<Object> buildMultiLineCharts(JsonNode field, JsonNode slot) {
		JsonNode data = resolveDataArray(slot);
		if (data == null || data.isEmpty()) return List.of();
		String groupKey = field.path("group_key").asText("group");
		String xKey = field.path("x_key").asText("eventTime");
		String yKey = field.path("y_key").asText(field.path("value_key").asText("value"));
		String label = field.path("label").asText("Multi-line");

		Map<String, ArrayNode> groups = new LinkedHashMap<>();
		for (JsonNode row : data) {
			String g = row.path(groupKey).asText("default");
			groups.computeIfAbsent(g, k -> mapper.createArrayNode()).add(row);
		}

		List<Object> out = new ArrayList<>();
		int idx = 0;
		for (Map.Entry<String, ArrayNode> e : groups.entrySet()) {
			idx++;
			ObjectNode chart = mapper.createObjectNode();
			chart.put("type", "line");
			chart.put("title", label + " — " + e.getKey() + " (" + idx + "/" + groups.size() + ")");
			chart.put("x", xKey);
			ArrayNode ys = mapper.createArrayNode();
			ys.add(yKey);
			chart.set("y", ys);
			chart.set("data", e.getValue());
			out.add(chart);
		}
		return out;
	}

	/** Simple line/bar/scatter. */
	private Object buildSimpleChart(String type, JsonNode field, JsonNode slot) {
		JsonNode data = resolveDataArray(slot);
		if (data == null) return null;
		String frontendType = switch (type) {
			case "line_chart" -> "line";
			case "bar_chart" -> "bar";
			case "scatter_chart" -> "scatter";
			default -> "line";
		};
		String xKey = field.path("x_key").asText("eventTime");
		// y column: prefer explicit value_key / y_key; else first non-x numeric col
		String yKey = field.path("value_key").asText(
				field.path("y_key").asText(null));
		if (yKey == null && data.size() > 0) {
			for (java.util.Iterator<String> it = data.get(0).fieldNames(); it.hasNext(); ) {
				String f = it.next();
				if (!f.equals(xKey) && data.get(0).get(f).isNumber()) {
					yKey = f;
					break;
				}
			}
		}
		if (yKey == null) yKey = "value";

		ObjectNode chart = mapper.createObjectNode();
		chart.put("type", frontendType);
		chart.put("title", field.path("label").asText(field.path("key").asText("chart")));
		chart.put("x", xKey);
		ArrayNode ys = mapper.createArrayNode();
		ys.add(yKey);
		// y_keys from schema (multi-series line_chart)
		JsonNode yKeys = field.get("y_keys");
		if (yKeys != null && yKeys.isArray()) {
			ys = mapper.createArrayNode();
			yKeys.forEach(ys::add);
		}
		chart.set("y", ys);
		chart.set("data", data);

		// Highlight for line_chart (OOC markers etc)
		String highlightKey = field.path("highlight_key").asText(null);
		if (highlightKey != null && !highlightKey.isBlank()) {
			ObjectNode hl = mapper.createObjectNode();
			hl.put("field", highlightKey);
			hl.put("eq", true);
			chart.set("highlight", hl);
		}
		return chart;
	}

	/** Pipelines may emit either a raw [...] or {data:[...], ...}. Normalize. */
	private JsonNode resolveDataArray(JsonNode slot) {
		if (slot.isArray()) return slot;
		if (slot.isObject()) {
			JsonNode d = slot.get("data");
			if (d != null && d.isArray()) return d;
		}
		return null;
	}
}
