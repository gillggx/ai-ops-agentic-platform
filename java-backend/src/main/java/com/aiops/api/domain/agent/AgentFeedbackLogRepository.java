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

	@Query("SELECT f FROM AgentFeedbackLogEntity f "
			+ "WHERE (:since IS NULL OR f.createdAt >= :since) "
			+ "ORDER BY f.createdAt DESC")
	List<AgentFeedbackLogEntity> findRecent(
			@Param("since") OffsetDateTime since,
			Pageable pageable);
}
