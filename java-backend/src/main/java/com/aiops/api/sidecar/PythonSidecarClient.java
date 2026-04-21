package com.aiops.api.sidecar;

import com.aiops.api.auth.AuthPrincipal;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.stream.Collectors;

/**
 * Thin wrapper around the WebClient pointed at the Python sidecar.
 *
 * <p>Responsibilities:
 * <ul>
 *   <li>Inject caller identity headers ({@code X-User-Id}, {@code X-User-Roles})
 *       so the sidecar knows who requested, without re-issuing tokens.</li>
 *   <li>Expose both <em>JSON</em> and <em>SSE</em> proxy helpers.</li>
 * </ul>
 *
 * <p>The service token is already wired by {@link PythonSidecarConfig}.
 */
@Component
public class PythonSidecarClient {

	private static final ParameterizedTypeReference<ServerSentEvent<String>> SSE_STRING_TYPE =
			new ParameterizedTypeReference<>() {};

	private final WebClient webClient;

	public PythonSidecarClient(WebClient pythonSidecarWebClient) {
		this.webClient = pythonSidecarWebClient;
	}

	public <T> Mono<T> postJson(String path, Object body, Class<T> responseType, AuthPrincipal caller) {
		return webClient.post()
				.uri(path)
				.headers(h -> applyCallerHeaders(h, caller))
				.contentType(MediaType.APPLICATION_JSON)
				.bodyValue(body)
				.retrieve()
				.bodyToMono(responseType);
	}

	public <T> Mono<T> getJson(String path, Class<T> responseType, AuthPrincipal caller) {
		return webClient.get()
				.uri(path)
				.headers(h -> applyCallerHeaders(h, caller))
				.retrieve()
				.bodyToMono(responseType);
	}

	/** Streams SSE events from the sidecar 1:1 back to the caller. */
	public Flux<ServerSentEvent<String>> postSse(String path, Object body, AuthPrincipal caller) {
		return webClient.post()
				.uri(path)
				.headers(h -> applyCallerHeaders(h, caller))
				.accept(MediaType.TEXT_EVENT_STREAM)
				.contentType(MediaType.APPLICATION_JSON)
				.bodyValue(body)
				.retrieve()
				.bodyToFlux(SSE_STRING_TYPE);
	}

	private void applyCallerHeaders(HttpHeaders h, AuthPrincipal caller) {
		if (caller == null) return;
		if (caller.userId() != null) h.add("X-User-Id", String.valueOf(caller.userId()));
		if (caller.roles() != null && !caller.roles().isEmpty()) {
			h.add("X-User-Roles", caller.roles().stream().map(Enum::name).collect(Collectors.joining(",")));
		}
		if (caller.username() != null) h.add("X-User-Name", caller.username());
	}
}
