package com.aiops.api.common;

import org.springframework.http.HttpStatus;

import java.util.Map;

/**
 * Small parsing helpers for loosely-typed {@code Map<String, Object>}
 * request bodies — the shape we accept on a handful of endpoints that
 * tolerate both legacy camelCase (sent by Frontend clients before the
 * Java cutover) and canonical snake_case (Java wire convention).
 *
 * <p>Centralised 2026-05-23 (Phase 12 OOP refactor) — AgentProxyController
 * had 5 endpoints with identical 5-line "pick sessionId from camelCase,
 * fall back to snake_case, throw 400 if both blank" boilerplate. Moving
 * it here keeps the controller methods skinny and means a future fix to
 * the alias convention (e.g. drop legacy compat after Frontend redeploy)
 * lands in one place.
 *
 * <p>Pure helpers — no Spring dependency, no state. Lives in
 * {@code com.aiops.api.common} so any controller can import.
 */
public final class RequestBodyAccess {

	private RequestBodyAccess() {}

	/** Stringify a body value, or null if absent. */
	public static String asString(Object v) {
		return v == null ? null : v.toString();
	}

	/** Parse a body value as Long; null on absent / blank / unparseable. */
	public static Long asLong(Object v) {
		if (v == null) return null;
		if (v instanceof Number n) return n.longValue();
		String s = v.toString();
		if (s.isBlank()) return null;
		try { return Long.parseLong(s.trim()); } catch (NumberFormatException e) { return null; }
	}

	/** Pick the first non-blank value for any of the given aliases (e.g.
	 *  {@code pickAlias(body, "sessionId", "session_id")}). Returns null
	 *  when none present. */
	public static String pickAlias(Map<String, Object> body, String... aliases) {
		for (String a : aliases) {
			String v = asString(body.get(a));
			if (v != null && !v.isBlank()) return v;
		}
		return null;
	}

	/** Same as {@link #pickAlias} but throws a 400 ApiException with the
	 *  given field name when no alias has a non-blank value. */
	public static String requireAlias(Map<String, Object> body, String fieldName, String... aliases) {
		String v = pickAlias(body, aliases);
		if (v == null) {
			throw new ApiException(HttpStatus.BAD_REQUEST, "validation_error",
					fieldName + ": must not be blank");
		}
		return v;
	}

	/** Pick the first {@code Map<String, Object>} value for any alias.
	 *  Returns null when no alias resolves to a Map. */
	@SuppressWarnings("unchecked")
	public static Map<String, Object> pickMapAlias(Map<String, Object> body, String... aliases) {
		for (String a : aliases) {
			Object v = body.get(a);
			if (v instanceof Map<?, ?> m) return (Map<String, Object>) m;
		}
		return null;
	}

	/** Pick a boolean tolerant of Boolean / String / null. */
	public static boolean asBool(Object v) {
		if (v instanceof Boolean b) return b;
		return v != null && Boolean.parseBoolean(v.toString());
	}
}
