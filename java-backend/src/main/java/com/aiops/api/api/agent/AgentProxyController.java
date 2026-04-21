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
 * <p>Auth: PE or IT_ADMIN — On-duty read-only users don't hit the AI surface.
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/agent")
@PreAuthorize(Authorities.ADMIN_OR_PE)
public class AgentProxyController {

	private static final long SSE_TIMEOUT_MS = 10L * 60_000L;

	private final PythonSidecarClient sidecar;

	public AgentProxyController(PythonSidecarClient sidecar) {
		this.sidecar = sidecar;
	}

	// --- SSE paths: chat + build ---

	@PostMapping(path = "/chat", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	public SseEmitter chat(@Validated @RequestBody ChatRequest req,
	                       @AuthenticationPrincipal AuthPrincipal caller) {
		return bridgeSse(sidecar.postSse("/internal/agent/chat", req, caller), "chat");
	}

	@PostMapping(path = "/build", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	public SseEmitter build(@Validated @RequestBody BuildRequest req,
	                        @AuthenticationPrincipal AuthPrincipal caller) {
		return bridgeSse(sidecar.postSse("/internal/agent/build", req, caller), "build");
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
	@SuppressWarnings({"unchecked", "rawtypes"})
	public ApiResponse<Map> pipelineExecute(@RequestBody Map<String, Object> body,
	                                        @AuthenticationPrincipal AuthPrincipal caller) {
		Map result = sidecar.postJson("/internal/pipeline/execute", body, Map.class, caller).block();
		return ApiResponse.ok(result);
	}

	@PostMapping("/pipeline/validate")
	@SuppressWarnings({"unchecked", "rawtypes"})
	public ApiResponse<Map> pipelineValidate(@RequestBody Map<String, Object> body,
	                                         @AuthenticationPrincipal AuthPrincipal caller) {
		Map result = sidecar.postJson("/internal/pipeline/validate", body, Map.class, caller).block();
		return ApiResponse.ok(result);
	}

	@PostMapping("/sandbox/run")
	@SuppressWarnings({"unchecked", "rawtypes"})
	public ApiResponse<Map> sandbox(@RequestBody Map<String, Object> body,
	                                @AuthenticationPrincipal AuthPrincipal caller) {
		Map result = sidecar.postJson("/internal/sandbox/run", body, Map.class, caller).block();
		return ApiResponse.ok(result);
	}

	@GetMapping("/sidecar/health")
	@SuppressWarnings({"unchecked", "rawtypes"})
	public ApiResponse<Map> sidecarHealth(@AuthenticationPrincipal AuthPrincipal caller) {
		Map result = sidecar.getJson("/internal/health", Map.class, caller).block();
		return ApiResponse.ok(result);
	}

	// --- DTOs ---

	public record ChatRequest(@NotBlank String message, String sessionId) {}

	public record BuildRequest(@NotBlank String instruction, Long pipelineId, Map<String, Object> pipelineSnapshot) {}
}
