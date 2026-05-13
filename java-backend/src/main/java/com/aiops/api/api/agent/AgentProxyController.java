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
		// Phase E2/E3: when AIAgentPanel runs inside BuilderLayout it ships
		// `mode="builder"` plus `pipeline_snapshot` (the current canvas
		// pipeline_json with its declared inputs). Without this passthrough
		// the sidecar's mode-aware prompt never activates and Glass Box
		// sub-agent rebuilds without honoring declared $name inputs.
		String mode = asString(body.get("mode"));
		@SuppressWarnings("unchecked")
		Map<String, Object> pipelineSnapshot = body.get("pipelineSnapshot") instanceof Map<?, ?> ps1
				? (Map<String, Object>) ps1
				: body.get("pipeline_snapshot") instanceof Map<?, ?> ps2
						? (Map<String, Object>) ps2
						: null;
		ChatRequest req = new ChatRequest(message, sessionId, clientContext, mode, pipelineSnapshot);
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
		// 2026-05-13: pass triggerPayload through so sidecar's dry-run uses
		// the same inputs that production /run will. Without this, dry-run
		// uses canonical fallbacks (tool_id=EQP-01 etc.) which often differ
		// from the actual trigger and let runtime-only failures slip past
		// inspect/reflect.
		@SuppressWarnings("unchecked")
		Map<String, Object> triggerPayload = body.get("triggerPayload") instanceof Map<?, ?> tp1
				? (Map<String, Object>) tp1
				: body.get("trigger_payload") instanceof Map<?, ?> tp2
						? (Map<String, Object>) tp2
						: null;
		BuildRequest req = new BuildRequest(instruction, pipelineId, snapshot, triggerPayload);
		return bridgeSse(sidecar.postSse("/internal/agent/build", req, caller), "build");
	}

	// Phase 10 (graph_build v2) — resume a paused build at confirm_gate.
	// Body: { sessionId | session_id, confirmed: bool }
	@PostMapping(path = "/build/confirm", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public SseEmitter buildConfirm(@RequestBody Map<String, Object> body,
	                               @AuthenticationPrincipal AuthPrincipal caller) {
		String sessionId = asString(body.get("sessionId"));
		if (sessionId == null || sessionId.isBlank()) sessionId = asString(body.get("session_id"));
		if (sessionId == null || sessionId.isBlank()) {
			throw new com.aiops.api.common.ApiException(
					org.springframework.http.HttpStatus.BAD_REQUEST,
					"validation_error", "session_id: must not be blank");
		}
		Object confirmedRaw = body.get("confirmed");
		boolean confirmed = confirmedRaw instanceof Boolean b
				? b
				: confirmedRaw != null && Boolean.parseBoolean(confirmedRaw.toString());
		Map<String, Object> req = new java.util.HashMap<>();
		req.put("session_id", sessionId);
		req.put("confirmed", confirmed);
		return bridgeSse(sidecar.postSse("/internal/agent/build/confirm", req, caller), "build_confirm");
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

	public record ChatRequest(@NotBlank String message, String sessionId, Map<String, Object> clientContext,
	                          String mode, Map<String, Object> pipelineSnapshot) {}

	public record BuildRequest(
			@NotBlank String instruction,
			Long pipelineId,
			Map<String, Object> pipelineSnapshot,
			Map<String, Object> triggerPayload) {}
}
