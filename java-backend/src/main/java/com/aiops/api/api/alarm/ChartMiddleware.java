package com.aiops.api.api.alarm;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Component;

import java.util.*;

/**
 * Builds the {@code dr.charts[]} array the Frontend's ChartListRenderer expects.
 *
 * <p>Inputs:
 *   findings.outputs      — named data bags produced by the skill
 *   output_schema[]       — declares which outputs are chart-shaped
 *
 * <p>For each output_schema field whose {@code type} is in
 * {@link #CHART_TYPES}, we take the matching entry from {@code findings.outputs}
 * and emit a {@code ChartDSL}:
 *   { type, title, data, meta? }
 *
 * <p>This mirrors the Python chart_middleware.py behavior so the Frontend
 * renders identically to before cutover.
 */
@Component
public class ChartMiddleware {

	/** Schema types that are rendered as charts (not inline tables). */
	private static final Set<String> CHART_TYPES = Set.of(
			"spc_chart", "line_chart", "bar_chart", "scatter_chart", "multi_line_chart");

	private final ObjectMapper mapper;

	public ChartMiddleware(ObjectMapper mapper) {
		this.mapper = mapper;
	}

	/** Return chart DSL list, or empty list if no chart-type fields. */
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

			// SPC chart: field.group_key splits data by chart_type into sub-charts.
			if ("spc_chart".equals(type)) {
				charts.addAll(buildSpcCharts(field, slot));
			} else {
				charts.add(buildSimpleChart(type, field, slot));
			}
		}
		return charts;
	}

	private List<Object> buildSpcCharts(JsonNode field, JsonNode slot) {
		JsonNode data = slot.path("data");
		if (!data.isArray() || data.isEmpty()) return List.of();
		String groupKey = field.path("group_key").asText("chart_type");
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
			ObjectNode chart = mapper.createObjectNode();
			chart.put("type", "line");
			chart.put("title", e.getKey() + " — " + label + " (" + idx + "/" + groups.size() + ")");
			chart.set("data", e.getValue());
			// Frontend uses x_key / value_key / ucl_key / lcl_key / highlight_key for rendering
			copyIfPresent(chart, field, "x_key");
			copyIfPresent(chart, field, "value_key");
			copyIfPresent(chart, field, "ucl_key");
			copyIfPresent(chart, field, "lcl_key");
			copyIfPresent(chart, field, "highlight_key");
			out.add(chart);
		}
		return out;
	}

	private Object buildSimpleChart(String type, JsonNode field, JsonNode slot) {
		ObjectNode chart = mapper.createObjectNode();
		String frontendType = switch (type) {
			case "line_chart", "multi_line_chart" -> "line";
			case "bar_chart" -> "bar";
			case "scatter_chart" -> "scatter";
			default -> "line";
		};
		chart.put("type", frontendType);
		chart.put("title", field.path("label").asText(field.path("key").asText("chart")));
		// Data may be an array directly OR nested under slot.data
		JsonNode data = slot.isArray() ? slot : slot.path("data");
		if (data.isArray()) chart.set("data", data);
		else chart.set("data", mapper.createArrayNode());
		copyIfPresent(chart, field, "x_key");
		copyIfPresent(chart, field, "value_key");
		copyIfPresent(chart, field, "group_key");
		return chart;
	}

	private static void copyIfPresent(ObjectNode target, JsonNode source, String key) {
		JsonNode v = source.get(key);
		if (v != null && !v.isNull()) target.set(key, v);
	}
}
