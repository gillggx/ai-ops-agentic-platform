package com.aiops.api.api.aiops;

import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.config.AiopsProperties;
import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.domain.event.GeneratedEventEntity;
import com.aiops.api.domain.event.GeneratedEventRepository;
import org.springframework.beans.factory.annotation.Value;
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
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Dashboard briefing — quick aggregate view for on-duty users.
 * Rich analytics (LLM-generated summary) comes from the Python sidecar via
 * {@code /api/v1/agent/briefing}; this controller only returns the raw counts
 * the Frontend top bar needs for fast load.
 */
@RestController
@RequestMapping("/api/v1/briefing")
@PreAuthorize(Authorities.ANY_ROLE)
public class BriefingController {

	private static final long SSE_TIMEOUT_MS = 5L * 60_000L;

	private final AlarmRepository alarmRepo;
	private final GeneratedEventRepository eventRepo;
	private final AiopsProperties props;
	private final WebClient legacyBriefingClient;

	public BriefingController(AlarmRepository alarmRepo, GeneratedEventRepository eventRepo,
	                          AiopsProperties props,
	                          @Value("${aiops.legacy-backend-url:http://127.0.0.1:8001}") String legacyBackendUrl) {
		this.alarmRepo = alarmRepo;
		this.eventRepo = eventRepo;
		this.props = props;
		this.legacyBriefingClient = WebClient.builder()
				.baseUrl(legacyBackendUrl)
				.build();
	}

	@GetMapping
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

	// ── POST → SSE LLM-generated synthesis (proxied to legacy Python :8001) ──
	// Frontend alarm page posts {scope:"alarm" | "alarm_detail", alarmData:{...}}
	// and expects a streaming text response. The LLM logic still lives in the
	// Python stack (app/routers/briefing.py); until it ports to Java, proxy
	// the SSE stream transparently. The GET variant above is the fast path
	// (raw counts) used by the dashboard top bar.
	@PostMapping(produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	public SseEmitter postBriefing(@RequestBody Map<String, Object> body) {
		SseEmitter emitter = new SseEmitter(SSE_TIMEOUT_MS);

		String secret = props.auth() != null ? props.auth().sharedSecretToken() : null;
		if (secret == null || secret.isBlank()) {
			try {
				emitter.send(SseEmitter.event().data(
						"{\"error\":\"AIOPS_SHARED_SECRET_TOKEN not configured — cannot reach legacy briefing\"}"));
			} catch (IOException ignored) {}
			emitter.complete();
			return emitter;
		}

		Flux<ServerSentEvent<String>> upstream = legacyBriefingClient.post()
				.uri("/api/v1/briefing")
				.header("Authorization", "Bearer " + secret)
				.header("Content-Type", "application/json")
				.bodyValue(body)
				.retrieve()
				.bodyToFlux(new org.springframework.core.ParameterizedTypeReference<ServerSentEvent<String>>() {});

		AtomicReference<Disposable> subRef = new AtomicReference<>();
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
		subRef.set(sub);
		emitter.onCompletion(sub::dispose);
		emitter.onTimeout(sub::dispose);
		emitter.onError(e -> sub.dispose());
		return emitter;
	}
}
