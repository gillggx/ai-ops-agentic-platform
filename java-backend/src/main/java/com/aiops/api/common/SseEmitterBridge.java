package com.aiops.api.common;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.Disposable;
import reactor.core.publisher.Flux;

import java.io.IOException;

/**
 * Bridge a reactive {@code Flux<ServerSentEvent<String>>} (what
 * {@code WebClient.bodyToFlux} or {@code PythonSidecarClient.postSse}
 * returns) into Spring MVC's servlet-stack {@link SseEmitter}.
 *
 * <p>Centralised 2026-05-23 (Phase 12 OOP refactor) — three controllers
 * (AgentProxy, Briefing, SkillDocument) were carrying near-identical
 * subscribe / dispatch / cleanup blocks that drifted in small ways
 * (timeout, log tag, error swallow). Single source means the failure
 * semantics stay consistent and a future fix lands once.
 *
 * <p>Behaviour:
 * <ul>
 *   <li>Each upstream event re-emits with the same name/id/data
 *       (preserves SSE semantics).</li>
 *   <li>{@code IOException} on emit → client disconnected; complete
 *       quietly with error (logged at DEBUG only).</li>
 *   <li>Upstream error → log at WARN with tag, complete with error.</li>
 *   <li>Upstream completion → emitter.complete().</li>
 *   <li>Emitter timeout / error / completion → dispose subscription
 *       (no leaked reactor resources).</li>
 * </ul>
 */
@Slf4j
@Component
public class SseEmitterBridge {

	/** Default budget for long-running upstream streams (chat, build, briefing). */
	public static final long DEFAULT_TIMEOUT_MS = 10L * 60_000L;

	/** Bridge with default 10-minute timeout. */
	public SseEmitter bridge(Flux<ServerSentEvent<String>> upstream, String tag) {
		return bridge(upstream, tag, DEFAULT_TIMEOUT_MS);
	}

	/** Bridge with explicit timeout (ms). */
	public SseEmitter bridge(Flux<ServerSentEvent<String>> upstream, String tag, long timeoutMs) {
		SseEmitter emitter = new SseEmitter(timeoutMs);
		Disposable subscription = upstream.subscribe(
				ev -> {
					try {
						SseEmitter.SseEventBuilder builder = SseEmitter.event();
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
		emitter.onError(e -> subscription.dispose());
		emitter.onCompletion(subscription::dispose);
		return emitter;
	}
}
