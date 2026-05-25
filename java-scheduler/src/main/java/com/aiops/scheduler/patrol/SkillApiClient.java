package com.aiops.scheduler.patrol;

import com.aiops.scheduler.common.TraceIdFilter;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.ClientRequest;
import org.springframework.web.reactive.function.client.ExchangeFilterFunction;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.HashMap;
import java.util.Map;

/**
 * v6.1 (2026-05-20): thin client over java-api's
 * {@code POST /internal/skills/by-slug/{slug}/run-system} endpoint.
 *
 * <p>Used by SkillScheduleService + EventDispatchService to fire skills
 * with system-trigger tagging (so manual vs scheduler runs are
 * distinguishable in skill_runs.triggered_by).
 *
 * <p>Config (application.yml or env):
 * <ul>
 *   <li>{@code aiops.java-api.base-url} — default http://localhost:8002</li>
 *   <li>{@code aiops.java-api.internal-token} — same X-Internal-Token the
 *       sidecar uses; java-api accepts via InternalServiceTokenFilter</li>
 * </ul>
 */
@Slf4j
@Component
public class SkillApiClient {

	private final WebClient webClient;
	private final String internalToken;

	public SkillApiClient(@Value("${aiops.java-api.base-url:http://localhost:8002}") String baseUrl,
	                      @Value("${aiops.java-api.internal-token:}") String internalToken) {
		this.webClient = WebClient.builder()
				.baseUrl(baseUrl)
				.filter(traceIdPropagationFilter())
				.build();
		this.internalToken = internalToken == null ? "" : internalToken;
		if (this.internalToken.isBlank()) {
			log.warn("SkillApiClient: aiops.java-api.internal-token is empty — system-triggered skills will 401");
		}
	}

	private static ExchangeFilterFunction traceIdPropagationFilter() {
		return (request, next) -> {
			String tid = MDC.get(TraceIdFilter.MDC_KEY);
			if (tid == null || tid.isBlank()) return next.exchange(request);
			return next.exchange(ClientRequest.from(request)
					.header(TraceIdFilter.HEADER, tid).build());
		};
	}

	/**
	 * Fire-and-forget POST to java-api. Blocks briefly waiting for the 200
	 * ack (which java-api returns immediately after starting the async run),
	 * then returns. Returns true if dispatch was accepted, false on any
	 * error (logged).
	 */
	public boolean dispatchSkill(String slug, String triggeredBy, Map<String, Object> triggerPayload) {
		if (slug == null || slug.isBlank()) return false;
		Map<String, Object> body = new HashMap<>();
		body.put("triggered_by", triggeredBy != null ? triggeredBy : "system");
		body.put("trigger_payload", triggerPayload != null ? triggerPayload : Map.of());
		try {
			Map<?, ?> resp = webClient.post()
					.uri("/internal/skills/by-slug/{slug}/run-system", slug)
					.header("X-Internal-Token", internalToken)
					.contentType(MediaType.APPLICATION_JSON)
					.accept(MediaType.APPLICATION_JSON)
					.bodyValue(body)
					.retrieve()
					.bodyToMono(Map.class)
					.timeout(Duration.ofSeconds(10))
					.onErrorResume(ex -> {
						log.warn("dispatchSkill {} failed: {}", slug, ex.getMessage());
						return Mono.empty();
					})
					.block();
			if (resp == null) return false;
			log.info("dispatchSkill: slug={} triggered_by={} ack={}", slug, triggeredBy, resp);
			return true;
		} catch (Exception ex) {
			log.warn("dispatchSkill {} threw: {}", slug, ex.getMessage());
			return false;
		}
	}
}
