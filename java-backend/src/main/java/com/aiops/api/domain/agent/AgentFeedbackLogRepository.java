package com.aiops.api.domain.agent;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;

@Repository
public interface AgentFeedbackLogRepository extends JpaRepository<AgentFeedbackLogEntity, Long> {

	Optional<AgentFeedbackLogEntity> findBySessionIdAndMessageIdxAndUserId(
			String sessionId, Integer messageIdx, Long userId);

	/**
	 * Recent feedback rows newest-first, optionally filtered by lower-bound time.
	 * <p>Split into two methods because Postgres' JDBC driver can't infer a
	 * type for a NULL-typed parameter in ``:since IS NULL OR ...`` patterns
	 * (raises "could not determine data type of parameter $1").
	 */
	@Query("SELECT f FROM AgentFeedbackLogEntity f "
			+ "WHERE f.createdAt >= :since "
			+ "ORDER BY f.createdAt DESC")
	List<AgentFeedbackLogEntity> findRecentSince(
			@Param("since") OffsetDateTime since,
			Pageable pageable);

	@Query("SELECT f FROM AgentFeedbackLogEntity f ORDER BY f.createdAt DESC")
	List<AgentFeedbackLogEntity> findRecentAll(Pageable pageable);
}
