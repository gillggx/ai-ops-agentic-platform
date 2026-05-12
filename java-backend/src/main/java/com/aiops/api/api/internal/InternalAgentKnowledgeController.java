package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.agentknowledge.*;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

/**
 * Sidecar-only endpoints for retrieving agent knowledge during context_load.
 *
 * <p>The user-facing controller (/api/v1/agent-*) handles CRUD with auth;
 * this internal controller exposes scope-filtered queries for the sidecar
 * to fetch directives / knowledge / lexicon / examples relevant to the
 * current conversation, plus update endpoints for embeddings + usage stats.
 */
@RestController
@RequestMapping("/internal/agent-knowledge")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
@RequiredArgsConstructor
public class InternalAgentKnowledgeController {

    private final AgentDirectiveRepository directiveRepo;
    private final AgentDirectiveFireRepository fireRepo;
    private final AgentLexiconRepository lexiconRepo;
    private final AgentKnowledgeRepository knowledgeRepo;
    private final AgentExampleRepository exampleRepo;

    // ── Directives ────────────────────────────────────────────────────

    @GetMapping("/directives/active")
    public ApiResponse<List<DirectiveLite>> activeDirectives(
            @RequestParam("user_id") Long userId,
            @RequestParam(value = "skill_slug", required = false) String skillSlug,
            @RequestParam(value = "tool_id",   required = false) String toolId,
            @RequestParam(value = "recipe_id", required = false) String recipeId,
            @RequestParam(value = "limit", defaultValue = "8") int limit) {
        List<AgentDirectiveEntity> rows = directiveRepo.findActiveForScope(
                userId, skillSlug, toolId, recipeId, limit);
        return ApiResponse.ok(rows.stream().map(DirectiveLite::of).toList());
    }

    @PostMapping("/directives/{id}/fire")
    @Transactional
    public ApiResponse<Map<String, Object>> recordFire(
            @PathVariable("id") Long directiveId,
            @RequestBody Map<String, String> body) {
        if (!directiveRepo.existsById(directiveId)) {
            return ApiResponse.ok(Map.of("recorded", false, "reason", "directive not found"));
        }
        AgentDirectiveFireEntity e = new AgentDirectiveFireEntity();
        e.setDirectiveId(directiveId);
        e.setSessionId(body.get("session_id"));
        e.setContext(body.get("context"));
        fireRepo.save(e);
        return ApiResponse.ok(Map.of("recorded", true, "id", e.getId()));
    }

    // ── Lexicon ───────────────────────────────────────────────────────

    @GetMapping("/lexicon")
    public ApiResponse<List<LexiconLite>> lexicon(@RequestParam("user_id") Long userId) {
        return ApiResponse.ok(lexiconRepo.findByUserIdOrderByUsesDescTermAsc(userId)
                .stream().map(LexiconLite::of).toList());
    }

    @PostMapping("/lexicon/{id}/use")
    @Transactional
    public ApiResponse<Map<String, Object>> bumpLexiconUse(@PathVariable Long id) {
        AgentLexiconEntity e = lexiconRepo.findById(id).orElse(null);
        if (e == null) return ApiResponse.ok(Map.of("bumped", false));
        e.setUses(e.getUses() + 1);
        e.setUpdatedAt(OffsetDateTime.now());
        return ApiResponse.ok(Map.of("bumped", true, "uses", e.getUses()));
    }

    // ── Knowledge (RAG) ───────────────────────────────────────────────

    /** Sidecar passes a vector literal "[v1,v2,...]" computed from query. */
    @PostMapping("/knowledge/search")
    public ApiResponse<List<KnowledgeLite>> searchKnowledge(@RequestBody KnowledgeSearchRequest req) {
        if (req.queryVec() == null || req.queryVec().isBlank()) {
            return ApiResponse.ok(List.of());
        }
        List<AgentKnowledgeEntity> rows = knowledgeRepo.searchByEmbedding(
                req.userId(), req.queryVec(),
                req.skillSlug(), req.toolId(), req.recipeId(),
                req.limit() != null ? req.limit() : 3);
        return ApiResponse.ok(rows.stream().map(KnowledgeLite::of).toList());
    }

    /** PUT embedding for a knowledge row (called by sidecar after async embed).
     *  2026-05-12: was JPA save() but Hibernate emits `embedding=?` as VARCHAR
     *  and PostgreSQL refuses implicit VARCHAR → vector cast (SQLState 42804).
     *  Use the repository's native `CAST(?vec AS vector)` UPDATE instead. */
    @PutMapping("/knowledge/{id}/embedding")
    @Transactional
    public ApiResponse<Map<String, Object>> setKnowledgeEmbedding(
            @PathVariable Long id, @RequestBody Map<String, String> body) {
        String vec = body.get("embedding");
        if (vec == null || vec.isBlank()) {
            return ApiResponse.ok(Map.of("updated", false, "reason", "empty embedding"));
        }
        int affected = knowledgeRepo.updateEmbedding(id, vec);
        return ApiResponse.ok(Map.of("updated", affected > 0, "affected", affected));
    }

    @PostMapping("/knowledge/{id}/use")
    @Transactional
    public ApiResponse<Map<String, Object>> bumpKnowledgeUse(@PathVariable Long id) {
        AgentKnowledgeEntity e = knowledgeRepo.findById(id).orElse(null);
        if (e == null) return ApiResponse.ok(Map.of("bumped", false));
        e.setUses(e.getUses() + 1);
        e.setLastUsedAt(OffsetDateTime.now());
        return ApiResponse.ok(Map.of("bumped", true, "uses", e.getUses()));
    }

    /** List rows missing embedding so sidecar can backfill on a schedule. */
    @GetMapping("/knowledge/missing-embeddings")
    public ApiResponse<List<KnowledgeLite>> missingKnowledgeEmbeddings(
            @RequestParam(value = "limit", defaultValue = "20") int limit) {
        // simplest: filter list-all for null embedding; small dataset OK
        List<AgentKnowledgeEntity> all = knowledgeRepo.findAll();
        return ApiResponse.ok(all.stream()
                .filter(e -> e.getEmbedding() == null)
                .limit(limit)
                .map(KnowledgeLite::of)
                .toList());
    }

    /** 2026-05-12 — return all global high-priority knowledge regardless of
     *  embedding similarity. Cohere multilingual recall on long Chinese
     *  queries is patchy (verified empirically), so high-priority "first
     *  principle" entries (SPC/APC/FDC/Recipe/Skill-vs-Patrol architecture)
     *  must reach plan_node UNCONDITIONALLY, not gated on RAG cosine match.
     *  Small dataset (<30 high-priority rows expected) — full scan OK. */
    @GetMapping("/knowledge/high-priority")
    public ApiResponse<List<KnowledgeLite>> highPriorityKnowledge(
            @RequestParam(value = "user_id", defaultValue = "1") Long userId,
            @RequestParam(value = "limit", defaultValue = "20") int limit) {
        List<AgentKnowledgeEntity> all = knowledgeRepo.findAll();
        return ApiResponse.ok(all.stream()
                .filter(e -> e.getActive() != null && e.getActive())
                .filter(e -> "high".equalsIgnoreCase(e.getPriority()))
                .filter(e -> "global".equals(e.getScopeType())
                          || (e.getUserId() != null && e.getUserId().equals(userId)))
                .limit(limit)
                .map(KnowledgeLite::of)
                .toList());
    }

    // ── Examples (few-shot) ───────────────────────────────────────────

    @PostMapping("/examples/search")
    public ApiResponse<List<ExampleLite>> searchExamples(@RequestBody ExampleSearchRequest req) {
        if (req.queryVec() == null || req.queryVec().isBlank()) {
            return ApiResponse.ok(List.of());
        }
        List<AgentExampleEntity> rows = exampleRepo.searchByEmbedding(
                req.userId(), req.queryVec(),
                req.skillSlug(), req.toolId(), req.recipeId(),
                req.limit() != null ? req.limit() : 2);
        return ApiResponse.ok(rows.stream().map(ExampleLite::of).toList());
    }

    @PutMapping("/examples/{id}/embedding")
    @Transactional
    public ApiResponse<Map<String, Object>> setExampleEmbedding(
            @PathVariable Long id, @RequestBody Map<String, String> body) {
        // Same pgvector caveat as setKnowledgeEmbedding — use native cast.
        String vec = body.get("embedding");
        if (vec == null || vec.isBlank()) {
            return ApiResponse.ok(Map.of("updated", false, "reason", "empty embedding"));
        }
        int affected = exampleRepo.updateEmbedding(id, vec);
        return ApiResponse.ok(Map.of("updated", affected > 0, "affected", affected));
    }

    @GetMapping("/examples/missing-embeddings")
    public ApiResponse<List<ExampleLite>> missingExampleEmbeddings(
            @RequestParam(value = "limit", defaultValue = "20") int limit) {
        List<AgentExampleEntity> all = exampleRepo.findAll();
        return ApiResponse.ok(all.stream()
                .filter(e -> e.getEmbedding() == null)
                .limit(limit)
                .map(ExampleLite::of)
                .toList());
    }

    // ── Lite DTOs (slim wire shape) ───────────────────────────────────

    public record DirectiveLite(Long id, String scopeType, String scopeValue,
                                 String title, String body, String priority) {
        static DirectiveLite of(AgentDirectiveEntity e) {
            return new DirectiveLite(e.getId(), e.getScopeType(), e.getScopeValue(),
                    e.getTitle(), e.getBody(), e.getPriority());
        }
    }

    public record LexiconLite(Long id, String term, String standard, String note) {
        static LexiconLite of(AgentLexiconEntity e) {
            return new LexiconLite(e.getId(), e.getTerm(), e.getStandard(), e.getNote());
        }
    }

    public record KnowledgeLite(Long id, String scopeType, String scopeValue,
                                 String title, String body, String priority) {
        static KnowledgeLite of(AgentKnowledgeEntity e) {
            return new KnowledgeLite(e.getId(), e.getScopeType(), e.getScopeValue(),
                    e.getTitle(), e.getBody(), e.getPriority());
        }
    }

    public record ExampleLite(Long id, String scopeType, String scopeValue,
                              String title, String inputText, String outputText) {
        static ExampleLite of(AgentExampleEntity e) {
            return new ExampleLite(e.getId(), e.getScopeType(), e.getScopeValue(),
                    e.getTitle(), e.getInputText(), e.getOutputText());
        }
    }

    public record KnowledgeSearchRequest(
            Long userId, String queryVec,
            String skillSlug, String toolId, String recipeId, Integer limit) {}

    public record ExampleSearchRequest(
            Long userId, String queryVec,
            String skillSlug, String toolId, String recipeId, Integer limit) {}
}
