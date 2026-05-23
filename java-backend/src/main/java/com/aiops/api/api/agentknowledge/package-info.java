/**
 * User-owned Agent Rules + Knowledge HTTP layer + business service.
 *
 * <p>Layering (Phase 12 OOP refactor 2026-05-23):
 * <ul>
 *   <li>{@link com.aiops.api.api.agentknowledge.AgentKnowledgeController}
 *       — thin HTTP for 17 endpoints across 4 user-scoped resources
 *       (Directives / Lexicon / Knowledge / Examples).</li>
 *   <li>{@link com.aiops.api.api.agentknowledge.AgentKnowledgeService}
 *       — single service with 4 sections matching the resource boundary;
 *       owns scope/priority validation, ownership check, entity
 *       construction, and embedding invalidation on body/input change
 *       (via {@code clearEmbedding} native SQL — see commit e03020d for
 *       why JPA save() can't write pgvector columns).</li>
 *   <li>{@link com.aiops.api.api.agentknowledge.Dtos} — HTTP DTOs
 *       (CreateRequest / PatchRequest / read DTOs for the 4 resource
 *       types).</li>
 * </ul>
 *
 * <p>Sidecar-only reads (RAG search + embedding lifecycle + missing-
 * embedding backfill) live in
 * {@link com.aiops.api.api.internal.InternalAgentKnowledgeService} —
 * kept separate because the concerns differ (cross-user RAG vs user-
 * scoped CRUD with ownership).
 */
package com.aiops.api.api.agentknowledge;
