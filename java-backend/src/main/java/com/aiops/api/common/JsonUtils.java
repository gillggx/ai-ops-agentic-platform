package com.aiops.api.common;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.List;
import java.util.Map;

/**
 * JSON serdes helpers with "fall back to empty/null on failure" semantics.
 *
 * <p>Centralised 2026-05-23 (Phase 12 P2). Four services
 * (SkillDocumentService / SkillRunnerService / SkillAlarmEmitter /
 * SkillMaterializeService) each carried their own near-identical
 * {@code parseJsonObject}, {@code parseList}, and {@code safeJson}
 * helpers — same null/blank guard, same {@link JsonProcessingException}
 * catch, same empty-collection fallback. Single source means future
 * tweaks (e.g. log-on-parse-fail) land once.
 *
 * <p>Pure static — pass {@link ObjectMapper} as the first arg. No
 * {@code @Component} ceremony or per-service constructor injection.
 *
 * <p>Out of scope: helpers with non-empty fallback contracts (throw
 * ApiException, return caller-supplied default) stay in their owning
 * service — different contract.
 */
public final class JsonUtils {

	private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};
	private static final TypeReference<List<Map<String, Object>>> LIST_MAP_TYPE = new TypeReference<>() {};

	private JsonUtils() {}

	/** Parse {@code json} as a {@code Map<String, Object>}.
	 *  Returns {@link Map#of()} on null/blank input or any
	 *  {@link JsonProcessingException}. */
	public static Map<String, Object> parseObject(ObjectMapper mapper, String json) {
		if (json == null || json.isBlank()) return Map.of();
		try {
			return mapper.readValue(json, MAP_TYPE);
		} catch (JsonProcessingException e) {
			return Map.of();
		}
	}

	/** Parse {@code json} as a {@code List<Map<String, Object>>}.
	 *  Returns {@link List#of()} on null/blank input or any
	 *  {@link JsonProcessingException}. */
	public static List<Map<String, Object>> parseListOfObjects(ObjectMapper mapper, String json) {
		if (json == null || json.isBlank()) return List.of();
		try {
			return mapper.readValue(json, LIST_MAP_TYPE);
		} catch (JsonProcessingException e) {
			return List.of();
		}
	}

	/** Serialise {@code obj} to JSON text. Returns {@code null} for null
	 *  input or any {@link JsonProcessingException}. */
	public static String safeWrite(ObjectMapper mapper, Object obj) {
		if (obj == null) return null;
		try {
			return mapper.writeValueAsString(obj);
		} catch (JsonProcessingException e) {
			return null;
		}
	}

	/** Cast {@code o} to {@code Map<String, Object>} if it is a Map,
	 *  otherwise return {@link Map#of()}. No reflection / no copy. */
	@SuppressWarnings("unchecked")
	public static Map<String, Object> asMap(Object o) {
		return (o instanceof Map<?, ?>) ? (Map<String, Object>) o : Map.of();
	}
}
