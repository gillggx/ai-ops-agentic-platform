package com.aiops.api.domain.alarm;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.OffsetDateTime;
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
}
