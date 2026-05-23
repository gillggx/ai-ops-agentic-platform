/**
 * Internal (sidecar-only) HTTP layer. Auth gate:
 * {@code @PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)} — requires the
 * {@code X-Internal-Token} header.
 *
 * <p>Layering (Phase 12 OOP refactor 2026-05-23):
 * <ul>
 *   <li>{@link com.aiops.api.api.internal.InternalAgentKnowledgeController}
 *       — sidecar-facing RAG retrieval (knowledge / examples / directives
 *       / lexicon).</li>
 *   <li>{@link com.aiops.api.api.internal.InternalAgentKnowledgeService}
 *       — business logic: RAG search wiring, embedding lifecycle writes
 *       via native SQL, usage bumps, missing-embedding listing,
 *       high-priority global knowledge bypass. Stays separate from
 *       {@link com.aiops.api.api.agentknowledge.AgentKnowledgeService}
 *       (the public CRUD path) because the concerns differ: sidecar-
 *       driven cross-user RAG vs user-scoped CRUD with ownership.</li>
 * </ul>
 *
 * <p>Other internal controllers in this package follow the same auth
 * pattern (sidecar-only) but use the per-domain repository directly
 * since their endpoints are simple JPA passthroughs.
 */
package com.aiops.api.api.internal;
