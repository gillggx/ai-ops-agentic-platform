package com.aiops.api.domain.skill;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.OffsetDateTime;
import java.util.List;

@Repository
public interface ExecutionLogRepository extends JpaRepository<ExecutionLogEntity, Long> {
	List<ExecutionLogEntity> findBySkillIdOrderByStartedAtDesc(Long skillId);
	List<ExecutionLogEntity> findByAutoPatrolIdOrderByStartedAtDesc(Long autoPatrolId);

	// Bounded variants — avoid loading 40k+ rows into heap.
	List<ExecutionLogEntity> findBySkillIdOrderByStartedAtDesc(Long skillId, Pageable pageable);
	List<ExecutionLogEntity> findByAutoPatrolIdOrderByStartedAtDesc(Long autoPatrolId, Pageable pageable);

	// For alarm enrichment — fetch diagnostic logs (triggered_by like 'alarm:<id>') in bulk.
	List<ExecutionLogEntity> findByTriggeredByInOrderByStartedAtDesc(java.util.Collection<String> triggeredBy);

	/**
	 * V60 (2026-06-27): Patrol Activity side-panel drill query. Every filter
	 * is nullable — passing all-null is equivalent to {@code findAll(pageable)}
	 * (callers short-circuit that case to avoid the query overhead).
	 */
	@Query("""
	       SELECT e FROM ExecutionLogEntity e
	       WHERE (:skillId IS NULL OR e.skillId = :skillId)
	         AND (:after IS NULL OR e.startedAt >= :after)
	         AND (:before IS NULL OR e.startedAt < :before)
	         AND (:status IS NULL OR e.status = :status)
	       """)
	Page<ExecutionLogEntity> findFiltered(@Param("skillId") Long skillId,
	                                       @Param("after") OffsetDateTime after,
	                                       @Param("before") OffsetDateTime before,
	                                       @Param("status") String status,
	                                       Pageable pageable);
}
