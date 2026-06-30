package com.aiops.api.api.mcp;

import com.aiops.api.common.ApiException;
import com.aiops.api.common.JsonUtils;
import com.aiops.api.domain.mcp.McpDefinitionEntity;
import com.aiops.api.domain.mcp.McpDefinitionRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.net.URI;
import java.time.Duration;
import java.util.Map;

/**
 * Backs the System MCP admin "Sample Fetch / 試打資料" button. Dispatches the
 * MCP's own HTTP endpoint exactly the way the runtime block dispatcher does
 * ({@code python_ai_sidecar/pipeline_builder/blocks/mcp_call.py}): read
 * {@code api_config.endpoint_url / method / headers}, send the supplied params
 * as query string (GET) or JSON body (POST), and hand back the raw upstream
 * JSON so the admin renderer can show it as a table.
 *
 * <p>Returns the upstream payload verbatim (no flatten, no processing_script) —
 * the goal is "what does this MCP actually return", which must match the wire
 * the runtime sees. Upstream failures surface as {@link ApiException} with the
 * status + a body snippet so the UI shows a readable error instead of a 500.
 */
@Slf4j
@Service
public class McpSampleFetchService {

	private static final Duration TIMEOUT = Duration.ofSeconds(10);
	private static final int MAX_IN_MEMORY = 8 * 1024 * 1024;

	private final McpDefinitionRepository repository;
	private final ObjectMapper mapper;
	private final WebClient client;

	public McpSampleFetchService(McpDefinitionRepository repository, ObjectMapper mapper) {
		this.repository = repository;
		this.mapper = mapper;
		// No baseUrl — endpoint_url is an absolute address (typically the
		// simulator, e.g. http://localhost:8012/...). Per-request full URI.
		this.client = WebClient.builder()
				.codecs(c -> c.defaultCodecs().maxInMemorySize(MAX_IN_MEMORY))
				.build();
	}

	/**
	 * Invoke the MCP's endpoint with {@code params} and return the raw JSON.
	 *
	 * @param id     mcp_definitions.id
	 * @param params filled input fields (empty values already dropped client-side)
	 * @return upstream response parsed as JSON (object or array)
	 */
	public Object fetch(Long id, Map<String, Object> params) {
		McpDefinitionEntity mcp = repository.findById(id)
				.orElseThrow(() -> ApiException.notFound("mcp definition"));

		Map<String, Object> apiConfig = JsonUtils.parseObject(mapper, mcp.getApiConfig());
		String url = stringOrNull(apiConfig.get("endpoint_url"));
		String method = stringOrNull(apiConfig.get("method"));
		method = method == null ? "GET" : method.toUpperCase();
		Map<String, Object> headers = JsonUtils.asMap(apiConfig.get("headers"));

		if (url == null || url.isBlank()) {
			throw ApiException.badRequest(
					"MCP '" + mcp.getName() + "' 的 api_config 缺 endpoint_url，無法試打");
		}
		if (!"GET".equals(method) && !"POST".equals(method)) {
			throw ApiException.badRequest(
					"MCP '" + mcp.getName() + "' 不支援的 method '" + method + "'（僅 GET / POST）");
		}

		Map<String, Object> safeParams = params == null ? Map.of() : params;
		try {
			WebClient.RequestHeadersSpec<?> spec;
			if ("GET".equals(method)) {
				spec = client.get().uri(buildGetUri(url, safeParams));
			} else {
				spec = client.post().uri(URI.create(url)).bodyValue(safeParams);
			}

			String raw = spec
					.headers(h -> headers.forEach((k, v) -> {
						if (v != null) h.set(k, String.valueOf(v));
					}))
					.accept(MediaType.APPLICATION_JSON)
					.retrieve()
					.bodyToMono(String.class)
					.block(TIMEOUT);

			return parseBodyOrText(raw);
		} catch (WebClientResponseException e) {
			String snippet = e.getResponseBodyAsString();
			if (snippet != null && snippet.length() > 300) snippet = snippet.substring(0, 300) + "…";
			log.warn("MCP sample-fetch upstream error id={} {} {}: {}",
					id, method, url, e.getStatusCode());
			throw ApiException.badRequest(
					"MCP 端點回 " + e.getStatusCode().value() + "：" + snippet);
		} catch (RuntimeException e) {
			// reactor wraps connect/timeout/DNS as unchecked.
			log.warn("MCP sample-fetch unreachable id={} {} {}: {}", id, method, url, e.getMessage());
			throw ApiException.serviceUnavailable(
					"無法連到 MCP 端點 " + url + "：" + e.getMessage());
		}
	}

	/** Build an absolute URI with the params appended as the query string. */
	private URI buildGetUri(String url, Map<String, Object> params) {
		org.springframework.web.util.UriComponentsBuilder b =
				org.springframework.web.util.UriComponentsBuilder.fromUriString(url);
		params.forEach((k, v) -> {
			if (v != null) b.queryParam(k, String.valueOf(v));
		});
		return b.build(true).toUri();
	}

	/** Parse the body as JSON; fall back to a {text:...} envelope for non-JSON. */
	private Object parseBodyOrText(String raw) {
		if (raw == null || raw.isBlank()) return Map.of();
		try {
			return mapper.readValue(raw, Object.class);
		} catch (com.fasterxml.jackson.core.JsonProcessingException e) {
			String text = raw.length() > 2000 ? raw.substring(0, 2000) + "…" : raw;
			return Map.of("non_json_response", text);
		}
	}

	private static String stringOrNull(Object o) {
		return o == null ? null : String.valueOf(o);
	}
}
