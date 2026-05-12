package com.aiops.api.domain.agentknowledge;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

public interface AgentExampleRepository extends JpaRepository<AgentExampleEntity, Long> {
    List<AgentExampleEntity> findByUserIdOrderByCreatedAtDesc(Long userId);

    /** See AgentKnowledgeRepository.updateEmbedding — VARCHAR → vector
     *  implicit cast fails; force ::vector here. */
    @Modifying
    @Query(value = "UPDATE agent_examples SET embedding = CAST(:vec AS vector), updated_at = now() WHERE id = :id",
            nativeQuery = true)
    int updateEmbedding(@Param("id") Long id, @Param("vec") String vec);

    /** Top-K examples whose input_text most resembles current user query. */
    @Query(value = """
            SELECT * FROM agent_examples
            WHERE user_id = :userId
              AND embedding IS NOT NULL
              AND (scope_type = 'global'
                   OR (scope_type = 'skill'  AND scope_value = :skillSlug)
                   OR (scope_type = 'tool'   AND scope_value = :toolId)
                   OR (scope_type = 'recipe' AND scope_value = :recipeId))
            ORDER BY embedding <=> CAST(:queryVec AS vector)
            LIMIT :limit
            """, nativeQuery = true)
    List<AgentExampleEntity> searchByEmbedding(
            @Param("userId") Long userId,
            @Param("queryVec") String queryVec,
            @Param("skillSlug") String skillSlug,
            @Param("toolId") String toolId,
            @Param("recipeId") String recipeId,
            @Param("limit") int limit);
}
