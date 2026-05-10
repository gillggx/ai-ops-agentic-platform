package com.aiops.api.domain.agentknowledge;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

public interface AgentKnowledgeRepository extends JpaRepository<AgentKnowledgeEntity, Long> {
    List<AgentKnowledgeEntity> findByUserIdOrderByCreatedAtDesc(Long userId);

    /** Cosine-similarity search via pgvector. Embedding string is rendered
     *  as PostgreSQL vector literal '[0.1,0.2,...]'. Returns top-K most
     *  similar active rows matching scope. */
    @Query(value = """
            SELECT * FROM agent_knowledge
            WHERE user_id = :userId AND active = true
              AND embedding IS NOT NULL
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
            @Param("limit") int limit);
}
