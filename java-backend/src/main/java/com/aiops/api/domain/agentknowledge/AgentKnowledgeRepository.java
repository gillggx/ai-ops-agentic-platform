package com.aiops.api.domain.agentknowledge;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

public interface AgentKnowledgeRepository extends JpaRepository<AgentKnowledgeEntity, Long> {
    List<AgentKnowledgeEntity> findByUserIdOrderByCreatedAtDesc(Long userId);

    /** V75 review queue — deliberately CROSS-USER: ON_DUTY drafts live under
     *  the submitter's user_id, and the reviewing PE / IT_ADMIN is a different
     *  user. Callers must role-gate (AgentKnowledgeService.listDrafts). */
    List<AgentKnowledgeEntity> findByStatusOrderByCreatedAtDesc(String status);

    /** Curation input (V72): agent-written rows by class+active, e.g. draft
     *  corrections (active=false) or live preference/presentation dupes. */
    List<AgentKnowledgeEntity> findTop100ByMemoClassAndActiveOrderByIdDesc(
            String memoClass, Boolean active);

	/** V70 memory-layer dedup: same (user, class, title) → skip re-write. */
	java.util.Optional<AgentKnowledgeEntity> findFirstByUserIdAndMemoClassAndTitle(
			Long userId, String memoClass, String title);

    /** Native update for the embedding column. JPA's auto-generated UPDATE
     *  sends the embedding as VARCHAR, which PostgreSQL refuses to implicitly
     *  cast to `vector`. Use ?::vector here so the embedding string literal
     *  (e.g. "[0.1,0.2,...]") gets parsed by pgvector. */
    @Modifying
    @Query(value = "UPDATE agent_knowledge SET embedding = CAST(:vec AS vector), updated_at = now() WHERE id = :id",
            nativeQuery = true)
    int updateEmbedding(@Param("id") Long id, @Param("vec") String vec);

    /** Invalidate the embedding (used by the patch path when body text
     *  changes — sidecar's _backfill_embeddings will re-embed on next pass).
     *  Plain UPDATE works for NULL because we're not crossing a type cast. */
    @Modifying
    @Query(value = "UPDATE agent_knowledge SET embedding = NULL, updated_at = now() WHERE id = :id",
            nativeQuery = true)
    int clearEmbedding(@Param("id") Long id);

    /** Cosine-similarity search via pgvector. Embedding string is rendered
     *  as PostgreSQL vector literal '[0.1,0.2,...]'. Returns top-K most
     *  similar active rows matching scope.
     *
     *  <p>V58: optional {@code layer} filter ('plan'|'execute') keeps only
     *  entries whose applies_to matches the requesting layer (or 'both'). The
     *  filter runs BEFORE the cosine ORDER BY so ranking isn't polluted by
     *  wrong-layer rows. Pass {@code null} to disable (legacy behaviour). */
    @Query(value = """
            SELECT * FROM agent_knowledge
            WHERE user_id = :userId AND active = true
              AND status = 'active'
              AND embedding IS NOT NULL
              AND (CAST(:layer AS text) IS NULL
                   OR applies_to = :layer OR applies_to = 'both')
              AND (scope_type = 'global'
                   OR (scope_type = 'skill'  AND scope_value = :skillSlug)
                   OR (scope_type = 'tool'   AND scope_value = :toolId)
                   OR (scope_type = 'recipe' AND scope_value = :recipeId))
            ORDER BY embedding <=> CAST(:queryVec AS vector)
            LIMIT :limit
            """, nativeQuery = true)
    List<AgentKnowledgeEntity> searchByEmbedding(
            @Param("userId") Long userId,
            @Param("queryVec") String queryVec,
            @Param("skillSlug") String skillSlug,
            @Param("toolId") String toolId,
            @Param("recipeId") String recipeId,
            @Param("layer") String layer,
            @Param("limit") int limit);
}
