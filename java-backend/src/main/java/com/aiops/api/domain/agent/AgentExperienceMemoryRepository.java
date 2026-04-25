package com.aiops.api.domain.agent;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface AgentExperienceMemoryRepository extends JpaRepository<AgentExperienceMemoryEntity, Long> {

	List<AgentExperienceMemoryEntity> findByUserIdAndStatusOrderByLastUsedAtDesc(Long userId, String status);

	/**
	 * pgvector cosine similarity search.
	 * Returns rows ordered by ascending cosine distance (= descending similarity),
	 * filtered to ACTIVE status + non-null embedding + min confidence.
	 *
	 * <p>Each row in the result is {@code Object[]{ AgentExperienceMemoryEntity, Double similarity }}.
	 *
	 * <p>The {@code :queryVec} parameter is a pgvector literal in the form
	 * {@code "[0.1,0.2,...]"} — caller (controller) must format it.
	 */
	@Query(value = """
			SELECT m.*,
			       (1 - (m.embedding <=> CAST(:queryVec AS vector))) AS sim
			FROM agent_experience_memory m
			WHERE m.user_id = :userId
			  AND m.status = 'ACTIVE'
			  AND m.confidence_score >= :minConfidence
			  AND m.embedding IS NOT NULL
			ORDER BY m.embedding <=> CAST(:queryVec AS vector)
			LIMIT :topK
			""", nativeQuery = true)
	List<Object[]> searchByEmbedding(@Param("userId") Long userId,
	                                  @Param("queryVec") String queryVec,
	                                  @Param("topK") int topK,
	                                  @Param("minConfidence") int minConfidence);

	/**
	 * Closest existing memory for dedup. Returns at most 1 row.
	 * Same shape as {@link #searchByEmbedding}.
	 */
	@Query(value = """
			SELECT m.*,
			       (1 - (m.embedding <=> CAST(:queryVec AS vector))) AS sim
			FROM agent_experience_memory m
			WHERE m.user_id = :userId
			  AND m.status = 'ACTIVE'
			  AND m.embedding IS NOT NULL
			ORDER BY m.embedding <=> CAST(:queryVec AS vector)
			LIMIT 1
			""", nativeQuery = true)
	List<Object[]> findNearestForDedup(@Param("userId") Long userId,
	                                    @Param("queryVec") String queryVec);

	/** Atomic counter bump for feedback path. */
	@Modifying
	@Query(value = """
			UPDATE agent_experience_memory
			   SET success_count = success_count + :successDelta,
			       fail_count = fail_count + :failDelta,
			       last_used_at = NOW()
			 WHERE id = :id
			""", nativeQuery = true)
	int recordFeedback(@Param("id") Long id,
	                    @Param("successDelta") int successDelta,
	                    @Param("failDelta") int failDelta);

	/** Atomic confidence bump for dedup path (caps at MAX). */
	@Modifying
	@Query(value = """
			UPDATE agent_experience_memory
			   SET confidence_score = LEAST(confidence_score + 1, :maxConfidence),
			       updated_at = NOW()
			 WHERE id = :id
			""", nativeQuery = true)
	int bumpConfidence(@Param("id") Long id, @Param("maxConfidence") int maxConfidence);
}
