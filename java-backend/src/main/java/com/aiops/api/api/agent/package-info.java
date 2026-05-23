/**
 * Agent proxy + feedback HTTP layer.
 *
 * <p>Layering (Phase 12 OOP refactor 2026-05-23):
 * <ul>
 *   <li>{@link com.aiops.api.api.agent.AgentProxyController} — SSE +
 *       JSON proxy for the Python sidecar (chat / build / build-resume
 *       endpoints / pipeline execute / sandbox / sidecar health).
 *       Mostly thin transport with alias-compat body parsing
 *       (camelCase + snake_case) — no domain state lives here, so no
 *       service was extracted. Shared SSE wiring + body parsing live in
 *       {@link com.aiops.api.common.SseEmitterBridge} and
 *       {@link com.aiops.api.common.RequestBodyAccess}.</li>
 *   <li>{@link com.aiops.api.api.agent.AgentProxyDtos} — HTTP DTOs
 *       lifted out of the controller for consistency with the other
 *       refactored packages.</li>
 *   <li>{@link com.aiops.api.api.agent.AgentFeedbackController} — agent
 *       feedback CRUD (reactions / corrections).</li>
 *   <li>{@link com.aiops.api.api.agent.AgentToolController} — user-owned
 *       custom agent tools.</li>
 * </ul>
 */
package com.aiops.api.api.agent;
