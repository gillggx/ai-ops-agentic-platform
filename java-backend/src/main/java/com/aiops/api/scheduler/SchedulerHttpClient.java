package com.aiops.api.scheduler;

import com.aiops.api.common.ApiException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.time.Duration;
import java.util.Map;

/**
 * Phase 2 (project-restructure) — HTTP client used by the API service to
 * reach the new java-scheduler service for:
 *   - manual patrol trigger (sync, 30 s timeout — UI shows spinner)
 *   - cron sync after CRUD (best effort, fail-open)
 *   - generated_event / alarm dispatch fan-out (best effort, fail-open)
 *
 * <p>Fail-open contract:
 *   - {@link #triggerPatrol(Long)} throws on HTTP failure so the user sees
 *     a 503 (manual fire is interactive — silent fail would be worse than
 *     visible error).
 *   - {@link #syncPatrol(Long)} / {@link #dispatchEvent} / {@link #dispatchAlarm}
 *     swallow + warn-log so a scheduler outage doesn't break API CRUD.
 *     Drift is recovered by the scheduler's reconcileAll @Scheduled loop.
 */
@Slf4j
@Component
public class SchedulerHttpClient {

	private final WebClient client;
	private final String token;

	public SchedulerHttpClient(@Value("${aiops.scheduler.base-url:http://localhost:8003}") String baseUrl,
	                           @Value("${aiops.scheduler.internal-token:dev-only-do-not-use-in-prod}") String token) {
		this.client = WebClient.builder()
				.baseUrl(baseUrl)
				.codecs(c -> c.defaultCodecs().maxInMemorySize(4 * 1024 * 1024))
				.build();
		this.token = token;
	}

	/** Sync trigger — returns scheduler's PatrolRunResult dto-ish map. */
	@SuppressWarnings("unchecked")
	public Map<String, Object> triggerPatrol(Long patrolId) {
		try {
			Map<String, Object> body = client.post()
					.uri("/internal/scheduler/trigger/{id}", patrolId)
					.header("X-Internal-Token", token)
					.accept(MediaType.APPLICATION_JSON)
					.retrieve()
					.bodyToMono(Map.class)
					.block(Duration.ofSeconds(30));
			Object data = body == null ? null : body.get("data");
			return data instanceof Map ? (Map<String, Object>) data : Map.of();
		} catch (WebClientResponseException e) {
			throw ApiException.serviceUnavailable("scheduler trigger HTTP " + e.getStatusCode().value());
		} catch (Exception e) {
			throw ApiException.serviceUnavailable("scheduler unreachable: " + e.getMessage());
		}
	}

	/** Best-effort cron sync after patrol CRUD. */
	public void syncPatrol(Long patrolId) {
		try {
			client.post()
					.uri("/internal/scheduler/sync/{id}", patrolId)
					.header("X-Internal-Token", token)
					.retrieve()
					.toBodilessEntity()
					.block(Duration.ofSeconds(5));
		} catch (Exception e) {
			log.warn("scheduler sync failed for patrol {} (fail-open): {}", patrolId, e.getMessage());
		}
	}

	/** Fan out a generated_event row to event-mode patrols. Fail-open. */
	public void dispatchEvent(Long eventTypeId, String mappedParameters) {
		try {
			client.post()
					.uri("/internal/scheduler/dispatch-event")
					.header("X-Internal-Token", token)
					.contentType(MediaType.APPLICATION_JSON)
					.bodyValue(Map.of(
							"event_type_id", eventTypeId,
							"mapped_parameters", mappedParameters == null ? "" : mappedParameters
					))
					.retrieve()
					.toBodilessEntity()
					.block(Duration.ofSeconds(10));
		} catch (Exception e) {
			log.warn("scheduler dispatchEvent failed (fail-open): {}", e.getMessage());
		}
	}

	/** Fan out an alarm to auto_check pipelines. Fail-open. */
	public void dispatchAlarm(Long alarmId) {
		try {
			client.post()
					.uri("/internal/scheduler/dispatch-alarm/{id}", alarmId)
					.header("X-Internal-Token", token)
					.retrieve()
					.toBodilessEntity()
					.block(Duration.ofSeconds(10));
		} catch (Exception e) {
			log.warn("scheduler dispatchAlarm failed (fail-open): {}", e.getMessage());
		}
	}
}
