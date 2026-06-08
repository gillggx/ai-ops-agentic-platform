package com.aiops.scheduler.patrol;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

/**
 * POC skill-library branch — simulator removed.
 *
 * <p>Stubbed so AutoPatrolExecutor / EventPollerService callers keep
 * compiling and running. Both methods return empty so:
 *   - {@code all_equipment} scope expands to no tools (patrol does nothing)
 *   - event poll loop receives no events (poller still ticks, no-op)
 *
 * Restore from main branch once a replacement data source is wired.
 */
@Slf4j
@Component
public class SimulatorClient {

	private static volatile boolean warned;

	public SimulatorClient(ObjectMapper objectMapper) {
		// objectMapper kept on the signature so Spring's @Autowired wiring
		// stays unchanged; not used in the stub implementation.
	}

	private static void warnOnce() {
		if (!warned) {
			warned = true;
			log.info("SimulatorClient: simulator removed in POC — returning empty results");
		}
	}

	public List<Map<String, Object>> listAllTools() {
		warnOnce();
		return List.of();
	}

	public List<Map<String, Object>> listRecentEvents(String sinceIso, int limit) {
		warnOnce();
		return List.of();
	}
}
