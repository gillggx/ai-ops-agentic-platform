package com.aiops.api.api.aiops;

import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.domain.event.GeneratedEventEntity;
import com.aiops.api.domain.event.GeneratedEventRepository;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.Disposable;
import reactor.core.publisher.Flux;

import java.io.IOException;
import java.time.OffsetDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Dashboard briefing — LLM-generated operational summary + raw counts.
 *
 * <p>Phase 8-A-1d: SSE briefing now lives in the Python sidecar
 * ({@code python_ai_sidecar/routers/briefing.py}). This controller forwards
 * GET / POST to {@code /internal/briefing/sse} via the same
 * {@code pythonSidecarWebClient} the agent SSE paths use.
 *
 * <p>The {@code /api/v1/briefing} (no params) GET is unchanged — it returns
 * the raw alarm + event counts from Java DB, used by the dashboard top bar.
 */
@RestController
@RequestMapping("/api/v1/briefing")
public class BriefingController {

	private static final long SSE_TIMEOUT_MS = 5L * 60_000L;

	private final AlarmRepository alarmRepo;
	private final GeneratedEventRepository eventRepo;
	private final WebClient sidecarClient;

	public BriefingController(AlarmRepository alarmRepo, GeneratedEventRepository eventRepo,
	                          WebClient pythonSidecarWebClient) {
		this.alarmRepo = alarmRepo;
		this.eventRepo = eventRepo;
		this.sidecarClient = pythonSidecarWebClient;
	}

	// ── GET with scope → forward to sidecar SSE ──────────────────────────
	// Dashboard's BriefingPanel hits this with ?scope=fab|tool|alarm.
	// We translate the query string to a JSON body for the sidecar's POST.
	@GetMapping(params = "scope", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	public SseEmitter getBriefingSse(@RequestParam String scope,
	                                 @RequestParam(required = false) String toolId) {
		Map<String, Object> body = new HashMap<>();
		body.put("scope", scope);
		if (toolId != null && !toolId.isBlank()) body.put("toolId", toolId);
		return forwardToSidecar(body);
	}

	// GET without scope returns the legacy JSON snapshot (alarm counts) —
	// kept for any fast-path consumers that don't need LLM text.
	@GetMapping
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Map<String, Object>> summary(@RequestParam(defaultValue = "10") int recent) {
		int safeRecent = Math.max(1, Math.min(recent, 50));

		List<AlarmEntity> activeAlarms = alarmRepo.findByStatusOrderByCreatedAtDesc("active");
		List<AlarmEntity> recentAlarms = alarmRepo
				.findAll(PageRequest.of(0, safeRecent, Sort.by(Sort.Direction.DESC, "createdAt")))
				.getContent();
		List<GeneratedEventEntity> recentEvents = eventRepo
				.findAll(PageRequest.of(0, safeRecent, Sort.by(Sort.Direction.DESC, "createdAt")))
				.getContent();
		long pendingEvents = eventRepo.findByStatus("pending").size();

		return ApiResponse.ok(Map.of(
				"generated_at", OffsetDateTime.now(),
				"alarms", Map.of(
						"active", activeAlarms.size(),
						"recent", recentAlarms.stream().map(a -> Map.of(
								"id", a.getId(),
								"severity", a.getSeverity(),
								"title", a.getTitle(),
								"status", a.getStatus(),
								"created_at", a.getCreatedAt()
						)).toList()
				),
				"events", Map.of(
						"pending", pendingEvents,
						"recent", recentEvents.stream().map(e -> Map.of(
								"id", e.getId(),
								"event_type_id", e.getEventTypeId(),
								"status", e.getStatus(),
								"created_at", e.getCreatedAt()
						)).toList()
				)
		));
	}

	// ── POST → forward to sidecar SSE ────────────────────────────────────
	// Frontend alarm page posts {scope, toolId?, alarmData?}; we relay
	// the exact body since sidecar's BriefingRequest mirrors the schema.
	@PostMapping(produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	public SseEmitter postBriefing(@RequestBody Map<String, Object> body) {
		return forwardToSidecar(body);
	}

	// ── helpers ──────────────────────────────────────────────────────────

	private SseEmitter forwardToSidecar(Map<String, Object> body) {
		SseEmitter emitter = new SseEmitter(SSE_TIMEOUT_MS);

		Flux<ServerSentEvent<String>> upstream = sidecarClient.post()
				.uri("/internal/briefing/sse")
				.header("Content-Type", "application/json")
				.bodyValue(body)
				.retrieve()
				.bodyToFlux(new org.springframework.core.ParameterizedTypeReference<ServerSentEvent<String>>() {});

		Disposable sub = upstream.subscribe(
				ev -> {
					try {
						var builder = SseEmitter.event();
						if (ev.event() != null) builder.name(ev.event());
						if (ev.id() != null) builder.id(ev.id());
						if (ev.data() != null) builder.data(ev.data());
						emitter.send(builder);
					} catch (IOException ex) {
						emitter.completeWithError(ex);
					}
				},
				err -> emitter.completeWithError(err),
				emitter::complete
		);
		emitter.onCompletion(sub::dispose);
		emitter.onTimeout(sub::dispose);
		emitter.onError(e -> sub.dispose());
		return emitter;
	}
}
