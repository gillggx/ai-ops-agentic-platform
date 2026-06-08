package com.aiops.api.api.fleet;

import com.aiops.api.config.AiopsProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

/**
 * POC skill-library branch — simulator removed.
 *
 * <p>All methods stubbed to return empty so Fleet API endpoints stay
 * callable (no NPE / no 500) but Dashboard panels show empty state.
 * Restore from main branch once a replacement data source is wired.
 */
@Component
public class FleetSimulatorClient {

	private static final Logger log = LoggerFactory.getLogger(FleetSimulatorClient.class);
	private static volatile boolean warned;

	public FleetSimulatorClient(AiopsProperties props, ObjectMapper mapper) {
		// Constructor signature kept so downstream @Autowired wiring is unchanged.
	}

	private static void warnOnce() {
		if (!warned) {
			warned = true;
			log.info("FleetSimulatorClient: simulator removed in POC — returning empty results");
		}
	}

	public List<Map<String, Object>> fetchTools() {
		warnOnce();
		return List.of();
	}

	public Map<String, Map<String, Object>> fetchSummaryByTool() {
		warnOnce();
		return Map.of();
	}

	public int fetchTotalEvents() {
		warnOnce();
		return 0;
	}

	public List<Map<String, Object>> fetchProcessEvents(String toolId, int limit) {
		warnOnce();
		return List.of();
	}
}
