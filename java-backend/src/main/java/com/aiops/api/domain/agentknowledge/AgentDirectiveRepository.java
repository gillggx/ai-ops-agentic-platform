package com.aiops.api.domain.agentknowledge;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

public interface AgentDirectiveRepository extends JpaRepository<AgentDirectiveEntity, Long> {
    List<AgentDirectiveEntity> findByUserIdOrderByCreatedAtDesc(Long userId);

    /** Active directives matching scope: global rows always included; specific
     *  scope rows included only when scope_type+value match (e.g. tool=EQP-09).
     *  Sorted by priority DESC (high → low) then specific-scope first. */
    @Query(value = """
            SELECT * FROM agent_directives
            WHERE user_id = :userId AND active = true
              AND (scope_type = 'global'
                   OR (scope_type = 'skill'  AND scope_value = :skillSlug)
                   OR (scope_type = 'tool'   AND scope_value = :toolId)
                   OR (scope_type = 'recipe' AND scope_value = :recipeId))
            ORDER BY
              CASE priority WHEN 'high' THEN 0 WHEN 'med' THEN 1 ELSE 2 END,
              CASE scope_type WHEN 'global' THEN 1 ELSE 0 END,
              created_at DESC
            LIMIT :limit
            """, nativeQuery = true)
    List<AgentDirectiveEntity> findActiveForScope(
            @Param("userId") Long userId,
            @Param("skillSlug") String skillSlug,
            @Param("toolId") String toolId,
            @Param("recipeId") String recipeId,
            @Param("limit") int limit);
}
