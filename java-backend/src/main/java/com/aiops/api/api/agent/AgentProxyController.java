package com.aiops.api.api.agent;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.sidecar.PythonSidecarClient;
import jakarta.validation.constraints.NotBlank;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.Disposable;

import java.io.IOException;
import java.util.Map;

/**
 * SSE + JSON proxy for everything that still runs in Python:
 * LangGraph chat, Pipeline Builder Glass Box, Pipeline Executor, Sandbox.
 *
 * <p>Design: we live in Spring MVC (servlet stack). Returning {@code Mono}/{@code Flux}
 * triggers async dispatch which confuses the stateless JWT filter. So JSON paths
 * {@code .block()} the {@code Mono} on the calling thread, and SSE paths bridge
 * the reactive {@code Flux} into an {@link SseEmitter} — which is the MVC-native
 * SSE primitive and plays nicely with the security filter chain.
 *
 * <p>Auth: chat is open to ANY_ROLE (ON_DUTY can ask the agent questions —
 * the sidecar's tool filter denies them build/write tools at the LLM layer);
 * build / pipeline.execute / sandbox.run stay PE+ since those are write paths.
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/agent")
public class AgentProxyController {

	private static final long SSE_TIMEOUT_MS = 10L * 60_000L;

	private final PythonSidecarClient sidecar;

	public AgentProxyController(PythonSidecarClient sidecar) {
		this.sidecar = sidecar;
	}

	// --- SSE paths: chat + build ---

	@PostMapping(path = "/chat", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	@PreAuthorize(Authorities.ANY_ROLE)
	public SseEmitter chat(@Validated @RequestBody ChatRequest req,
	                       @AuthenticationPrincipal AuthPrincipal caller) {
		return bridgeSse(sidecar.postSse("/internal/agent/chat", req, caller), "chat");
	}

	// Frontend historically posted to `/chat/stream` with a `prompt` field
	// (old Python FastAPI shape). Accept both paths and both field names so the
	// Next.js proxy keeps working post-cutover without a redeploy.
	@PostMapping(path = "/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	@PreAuthorize(Authorities.ANY_ROLE)
	public SseEmitter chatStreamCompat(@RequestBody Map<String, Object> body,
	                                   @AuthenticationPrincipal AuthPrincipal caller) {
		String message = asString(body.get("message"));
		if (message == null || message.isBlank()) message = asString(body.get("prompt"));
		if (message == null || message.isBlank()) {
			throw new com.aiops.api.common.ApiException(
					org.springframework.http.HttpStatus.BAD_REQUEST,
					"validation_error", "message: must not be blank");
		}
		String sessionId = asString(body.get("sessionId"));
		if (sessionId == null || sessionId.isBlank()) sessionId = asString(body.get("session_id"));
		// Part B: forward client_context (selected_equipment_id etc.) if present.
		// Accept both camelCase and snake_case from the frontend.
		@SuppressWarnings("unchecked")
		Map<String, Object> clientContext = body.get("clientContext") instanceof Map<?, ?> m1
				? (Map<String, Object>) m1
				: body.get("client_context") instanceof Map<?, ?> m2
						? (Map<String, Object>) m2
						: null;
		ChatRequest req = new ChatRequest(message, sessionId, clientContext);
		return bridgeSse(sidecar.postSse("/internal/agent/chat", req, caller), "chat");
	}

	private static String asString(Object v) {
		return v == null ? null : v.toString();
	}

	// Accepts both the new contract ({instruction, pipelineId, pipelineSnapshot})
	// and the legacy Python-era contract ({prompt, base_pipeline_id, base_pipeline})
	// so Frontend clients that were not redeployed with the Java cutover keep working.
	// Mirrors the chatStreamCompat pattern above.
	@PostMapping(path = "/build", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public SseEmitter build(@RequestBody Map<String, Object> body,
	                        @AuthenticationPrincipal AuthPrincipal caller) {
		String instruction = asString(body.get("instruction"));
		if (instruction == null || instruction.isBlank()) instruction = asString(body.get("prompt"));
		if (instruction == null || instruction.isBlank()) {
			throw new com.aiops.api.common.ApiException(
					org.springframework.http.HttpStatus.BAD_REQUEST,
					"validation_error", "instruction: must not be blank");
		}
		Long pipelineId = asLong(body.get("pipelineId"));
		if (pipelineId == null) pipelineId = asLong(body.get("base_pipeline_id"));
		@SuppressWarnings("unchecked")
		Map<String, Object> snapshot = body.get("pipelineSnapshot") instanceof Map<?, ?> m1
				? (Map<String, Object>) m1
				: body.get("base_pipeline") instanceof Map<?, ?> m2
						? (Map<String, Object>) m2
						: null;
		BuildRequest req = new BuildRequest(instruction, pipelineId, snapshot);
		return bridgeSse(sidecar.postSse("/internal/agent/build", req, caller), "build");
	}

	// SPEC_glassbox_continuation — resume a paused build.
	@PostMapping(path = "/build/continue", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public SseEmitter buildContinue(@RequestBody Map<String, Object> body,
	                                @AuthenticationPrincipal AuthPrincipal caller) {
		String sessionId = asString(body.get("sessionId"));
		if (sessionId == null || sessionId.isBlank()) sessionId = asString(body.get("session_id"));
		if (sessionId == null || sessionId.isBlank()) {
			throw new com.aiops.api.common.ApiException(
					org.springframework.http.HttpStatus.BAD_REQUEST,
					"validation_error", "session_id: must not be blank");
		}
		Long additional = asLong(body.get("additionalTurns"));
		if (additional == null) additional = asLong(body.get("additional_turns"));
		Map<String, Object> req = new java.util.HashMap<>();
		req.put("session_id", sessionId);
		req.put("additional_turns", additional != null ? additional : 20L);
		return bridgeSse(sidecar.postSse("/internal/agent/build/continue", req, caller), "build_continue");
	}

	private static Long asLong(Object v) {
		if (v == null) return null;
		if (v instanceof Number n) return n.longValue();
		String s = v.toString();
		if (s.isBlank()) return null;
		try { return Long.parseLong(s.trim()); } catch (NumberFormatException e) { return null; }
	}

	private SseEmitter bridgeSse(reactor.core.publisher.Flux<ServerSentEvent<String>> upstream, String tag) {
		SseEmitter emitter = new SseEmitter(SSE_TIMEOUT_MS);
		Disposable subscription = upstream.subscribe(
				ev -> {
					try {
						var builder = SseEmitter.event();
						if (ev.event() != null) builder.name(ev.event());
						if (ev.id() != null) builder.id(ev.id());
						if (ev.data() != null) builder.data(ev.data());
						emitter.send(builder);
					} catch (IOException ex) {
						log.debug("SSE client gone on {}: {}", tag, ex.getMessage());
						emitter.completeWithError(ex);
					}
				},
				err -> {
					log.warn("SSE upstream error on {}: {}", tag, err.toString());
					emitter.completeWithError(err);
				},
				emitter::complete
		);
		emitter.onTimeout(subscription::dispose);
		emitter.onError(err -> subscription.dispose());
		emitter.onCompletion(subscription::dispose);
		return emitter;
	}

	// --- JSON paths: pipeline + sandbox (block() is intentional) ---

	@PostMapping("/pipeline/execute")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	@SuppressWarnings({"unchecked", "rawtypes"})
	public ApiResponse<Map> pipelineExecute(@RequestBody Map<String, Object> body,
	                                        @AuthenticationPrincipal AuthPrincipal caller) {
		Map result = sidecar.postJson("/internal/pipeline/execute", body, Map.class, caller).block();
		return ApiResponse.ok(result);
	}

	@PostMapping("/pipeline/validate")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	@SuppressWarnings({"unchecked", "rawtypes"})
	public ApiResponse<Map> pipelineValidate(@RequestBody Map<String, Object> body,
	                                         @AuthenticationPrincipal AuthPrincipal caller) {
		Map result = sidecar.postJson("/internal/pipeline/validate", body, Map.class, caller).block();
		return ApiResponse.ok(result);
	}

	@PostMapping("/sandbox/run")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	@SuppressWarnings({"unchecked", "rawtypes"})
	public ApiResponse<Map> sandbox(@RequestBody Map<String, Object> body,
	                                @AuthenticationPrincipal AuthPrincipal caller) {
		Map result = sidecar.postJson("/internal/sandbox/run", body, Map.class, caller).block();
		return ApiResponse.ok(result);
	}

	@GetMapping("/sidecar/health")
	@PreAuthorize(Authorities.ANY_ROLE)
	@SuppressWarnings({"unchecked", "rawtypes"})
	public ApiResponse<Map> sidecarHealth(@AuthenticationPrincipal AuthPrincipal caller) {
		Map result = sidecar.getJson("/internal/health", Map.class, caller).block();
		return ApiResponse.ok(result);
	}

	// --- DTOs ---

	public record ChatRequest(@NotBlank String message, String sessionId, Map<String, Object> clientContext) {}

	public record BuildRequest(@NotBlank String instruction, Long pipelineId, Map<String, Object> pipelineSnapshot) {}
}
