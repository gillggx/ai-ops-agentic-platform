/**
 * Cross-cutting infrastructure: error envelope, exception type, shared
 * SSE bridge, JSON helpers, request-body alias parsing.
 *
 * <p>Phase 12 OOP refactor (2026-05-23) consolidated 4 duplicated
 * helpers from across the api packages:
 * <ul>
 *   <li>{@link com.aiops.api.common.ApiResponse} — uniform envelope
 *       {@code {ok, data, error, timestamp}} for all REST responses.</li>
 *   <li>{@link com.aiops.api.common.ApiException} — checked-via-rethrow
 *       error carrier mapped to HTTP status by
 *       {@code @ControllerAdvice}.</li>
 *   <li>{@link com.aiops.api.common.SseEmitterBridge} — bridges reactive
 *       {@code Flux<ServerSentEvent>} (WebClient.bodyToFlux output) into
 *       MVC's {@link org.springframework.web.servlet.mvc.method.annotation.SseEmitter}.
 *       Used by AgentProxy + Briefing + SkillDocument controllers.</li>
 *   <li>{@link com.aiops.api.common.RequestBodyAccess} — helpers for the
 *       camelCase + snake_case alias-compat pattern that 5+ endpoints
 *       used to repeat inline.</li>
 *   <li>{@link com.aiops.api.common.JsonUtils} — null/blank/parse-fail-
 *       fallback Jackson helpers shared by 4 services.</li>
 * </ul>
 *
 * <p>Add new helpers here when ≥2 services need the same pattern; never
 * earlier (YAGNI).
 */
package com.aiops.api.common;
