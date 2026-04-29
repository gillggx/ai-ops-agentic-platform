package com.aiops.api.domain.patrol;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface AutoPatrolRepository extends JpaRepository<AutoPatrolEntity, Long> {
	List<AutoPatrolEntity> findByIsActiveTrue();
	List<AutoPatrolEntity> findByTriggerMode(String triggerMode);
	List<AutoPatrolEntity> findByPipelineId(Long pipelineId);

	/** Phase C — event-mode dispatch lookup. Used by EventDispatchService when
	 *  a generated_events row is written to find every active patrol that
	 *  should fire on this event_type. */
	List<AutoPatrolEntity> findByTriggerModeAndEventTypeIdAndIsActiveTrue(
			String triggerMode, Long eventTypeId);
}
