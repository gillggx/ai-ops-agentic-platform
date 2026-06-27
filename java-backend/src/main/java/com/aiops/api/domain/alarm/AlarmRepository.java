package com.aiops.api.domain.alarm;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.OffsetDateTime;
import java.util.Collection;
import java.util.List;

@Repository
public interface AlarmRepository extends JpaRepository<AlarmEntity, Long> {
	List<AlarmEntity> findByStatusOrderByCreatedAtDesc(String status);
	List<AlarmEntity> findBySkillIdOrderByCreatedAtDesc(Long skillId);

	// Stats count — avoids loading 4k alarm rows into heap just to group by severity.
	@Query(value = "SELECT LOWER(COALESCE(severity, 'medium')) AS sev, COUNT(*) AS c "
			+ "FROM alarms WHERE (:status IS NULL OR status = :status) "
			+ "GROUP BY LOWER(COALESCE(severity, 'medium'))", nativeQuery = true)
	List<Object[]> countBySeverityGrouped(@Param("status") String status);

	/** Used by AlarmClusterService.computeClusters — pulls every alarm in
	 *  the time window (defaults to last 24h on the controller) into memory
	 *  for grouping. Indexed by event_time so this stays cheap up to ~10k
	 *  rows; we group by equipment_id in Java rather than SQL because
	 *  sparkline + bay derivation are easier in app code. */
	List<AlarmEntity> findByEventTimeAfterOrderByEventTimeDesc(OffsetDateTime since);

	/** Cluster-level batch ack — fetch every active alarm for one tool. */
	List<AlarmEntity> findByEquipmentIdAndStatus(String equipmentId, String status);

	/** Phase 11 — past-event replay: find recent alarms triggered by a given
	 *  event_type. Used by Skill Test modal's Past event tab. */
	List<AlarmEntity> findTop30ByTriggerEventOrderByCreatedAtDesc(String triggerEvent);

	/** v30.13 (2026-05-17) — SkillRunner alarm-emit dedup: return true if
	 *  there's already an active alarm for the same (skill, equipment) within
	 *  the given window. Used to avoid hourly-patrol spamming when condition
	 *  persists across multiple ticks. */
	@Query("SELECT COUNT(a) > 0 FROM AlarmEntity a "
			+ "WHERE a.status = 'active' "
			+ "  AND a.skillId = :skillId "
			+ "  AND a.equipmentId = :equipmentId "
			+ "  AND a.createdAt >= :since")
	boolean existsActiveBySkillAndEquipmentSince(@Param("skillId") Long skillId,
	                                              @Param("equipmentId") String equipmentId,
	                                              @Param("since") OffsetDateTime since);

	/** V60 (2026-06-27) — Patrol Activity bulk-fetch: load every alarm whose
	 *  skill_run_id is in the page's run-id set. Empty collection short-circuits
	 *  to empty list so callers can skip the existence check. */
	@Query("SELECT a FROM AlarmEntity a WHERE a.skillRunId IN :runIds")
	List<AlarmEntity> findBySkillRunIdIn(@Param("runIds") Collection<Long> runIds);

	/** V60 — Patrol Activity funnel: alarms emitted in time window. */
	@Query("SELECT COUNT(a) FROM AlarmEntity a "
			+ "WHERE a.createdAt >= :since AND a.createdAt < :until")
	long countByCreatedAtBetween(@Param("since") OffsetDateTime since,
	                              @Param("until") OffsetDateTime until);
}
