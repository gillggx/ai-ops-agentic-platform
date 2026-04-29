package com.aiops.api.patrol;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.List;
import java.util.Map;

/**
 * Thin client over the Ontology Simulator REST API ({@code :8012}).
 *
 * <p>Phase 5: only the {@code GET /api/v1/tools} endpoint is needed for
 * Auto-Patrol scope expansion — {@code all_equipment} returns the full list,
 * {@code by_step} filters that same list locally on a step match.
 */
@Slf4j
@Component
public class SimulatorClient {

	private static final TypeReference<List<Map<String, Object>>> TOOLS_TYPE = new TypeReference<>() {};

	private final WebClient webClient;
	private final ObjectMapper objectMapper;

	public SimulatorClient(@Value("${aiops.simulator.base-url}") String baseUrl,
	                       ObjectMapper objectMapper) {
		this.webClient = WebClient.builder().baseUrl(baseUrl).build();
		this.objectMapper = objectMapper;
	}

	/** Return all tools from the simulator. Returns empty list on any error
	 *  (we don't want a transient simulator hiccup to crash the patrol thread). */
	public List<Map<String, Object>> listAllTools() {
		try {
			String body = webClient.get()
					.uri("/api/v1/tools")
					.accept(MediaType.APPLICATION_JSON)
					.retrieve()
					.bodyToMono(String.class)
					.timeout(Duration.ofSeconds(10))
					.onErrorResume(ex -> {
						log.warn("simulator /tools failed: {}", ex.getMessage());
						return Mono.empty();
					})
					.block();
			if (body == null || body.isBlank()) return List.of();
			return objectMapper.readValue(body, TOOLS_TYPE);
		} catch (Exception ex) {
			log.warn("simulator parse failed: {}", ex.getMessage());
			return List.of();
		}
	}
}
