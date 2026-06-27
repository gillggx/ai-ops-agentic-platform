package com.aiops.api.domain.event;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.OffsetDateTime;
import java.util.List;

@Repository
public interface GeneratedEventRepository extends JpaRepository<GeneratedEventEntity, Long> {
	List<GeneratedEventEntity> findByEventTypeId(Long eventTypeId);
	List<GeneratedEventEntity> findByStatus(String status);

	/** V60 (2026-06-27) — Patrol Activity funnel: events received in window. */
	@Query("SELECT COUNT(e) FROM GeneratedEventEntity e "
			+ "WHERE e.createdAt >= :since AND e.createdAt < :until")
	long countByCreatedAtBetween(@Param("since") OffsetDateTime since,
	                              @Param("until") OffsetDateTime until);
}
