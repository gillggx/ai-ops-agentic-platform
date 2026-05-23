package com.aiops.api.api.fleet;

import com.aiops.api.config.AiopsProperties;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Shared simulator-HTTP infrastructure for the Fleet API surface.
 *
 * <p>Extracted from {@code FleetService} 2026-05-23 as part of the Phase 12
 * Java OOP refactor. The four fetch methods (tools roster, process summary,
 * total events, per-tool process events) were duplicated boilerplate around
 * {@code WebClient} + null/empty guards + Jackson conversion. Centralising
 * them lets {@link FleetRosterService} and
 * {@link FleetEquipmentDetailService} call a typed API instead of sharing
 * the WebClient bean.
 *
 * <p>All failures fail-open to empty lists/maps so the caller can degrade
 * gracefully when the simulator is unreachable — the Dashboard should still
 * render an "alarm-derived only" view rather than 500.
 */
@Slf4j
@Component
public class FleetSimulatorClient {

	private static final TypeReference<List<Map<String, Object>>> LIST_MAP_TYPE = new TypeReference<>() {};

	private final WebClient client;
	private final ObjectMapper mapper;

	public FleetSimulatorClient(AiopsProperties props, ObjectMapper mapper) {
		this.mapper = mapper;
		String simBase = props.simulator() != null && props.simulator().baseUrl() != null
				? props.simulator().baseUrl() : "http://localhost:8012";
		this.client = WebClient.builder()
				.baseUrl(simBase)
				.codecs(c -> c.defaultCodecs().maxInMemorySize(8 * 1024 * 1024))
				.build();
	}

	/** {@code GET /api/v1/tools} — normalised list of {tool_id, name, status}.
	 *  Empty list on failure. */
	public List<Map<String, Object>> fetchTools() {
		try {
			JsonNode root = client.get()
					.uri("/api/v1/tools")
					.retrieve()
					.bodyToMono(JsonNode.class)
					.block(Duration.ofSeconds(8));
			if (root == null) return List.of();
			JsonNode items = root.has("items") ? root.get("items") : root;
			if (items == null || !items.isArray()) return List.of();
			return mapper.convertValue(items, LIST_MAP_TYPE);
		} catch (Exception ex) {
			log.warn("simulator tools fetch failed: {}", ex.toString());
			return List.of();
		}
	}

	/** {@code GET /api/v1/process/summary?since=24h} — keyed by toolID for
	 *  fast per-tool lookup. Empty map on failure. */
	@SuppressWarnings("unchecked")
	public Map<String, Map<String, Object>> fetchSummaryByTool() {
		try {
			JsonNode root = client.get()
					.uri(uri -> uri.path("/api/v1/process/summary").queryParam("since", "24h").build())
					.retrieve()
					.bodyToMono(JsonNode.class)
					.block(Duration.ofSeconds(8));
			if (root == null) return Map.of();
			JsonNode arr = root.get("by_tool");
			if (arr == null || !arr.isArray()) return Map.of();
			Map<String, Map<String, Object>> out = new HashMap<>();
			for (JsonNode row : arr) {
				String id = row.path("toolID").asText(null);
				if (id == null) continue;
				out.put(id, mapper.convertValue(row, Map.class));
			}
			return out;
		} catch (Exception ex) {
			log.warn("simulator summary fetch failed: {}", ex.toString());
			return Map.of();
		}
	}

	/** Fab-wide total event count from {@code /api/v1/process/summary}.
	 *  Returns 0 on failure. */
	public int fetchTotalEvents() {
		try {
			JsonNode root = client.get()
					.uri(uri -> uri.path("/api/v1/process/summary").queryParam("since", "24h").build())
					.retrieve()
					.bodyToMono(JsonNode.class)
					.block(Duration.ofSeconds(5));
			if (root == null) return 0;
			return root.path("total_events").asInt(0);
		} catch (Exception ex) {
			log.warn("simulator total_events fetch failed: {}", ex.toString());
			return 0;
		}
	}

	/** Per-tool process events from {@code /api/v1/process/info}.
	 *  Empty list on failure. */
	public List<Map<String, Object>> fetchProcessEvents(String toolId, int limit) {
		try {
			JsonNode root = client.get()
					.uri(uri -> uri.path("/api/v1/process/info")
							.queryParam("toolID", toolId)
							.queryParam("limit", limit)
							.build())
					.retrieve()
					.bodyToMono(JsonNode.class)
					.block(Duration.ofSeconds(8));
			if (root == null) return List.of();
			JsonNode events = root.get("events");
			if (events == null || !events.isArray()) return List.of();
			return mapper.convertValue(events, LIST_MAP_TYPE);
		} catch (Exception ex) {
			log.warn("simulator process_info fetch failed for {}: {}", toolId, ex.toString());
			return List.of();
		}
	}
}
