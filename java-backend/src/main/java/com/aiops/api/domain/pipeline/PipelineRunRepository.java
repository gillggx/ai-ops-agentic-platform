package com.aiops.api.domain.pipeline;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface PipelineRunRepository extends JpaRepository<PipelineRunEntity, Long> {
	List<PipelineRunEntity> findByPipelineIdOrderByStartedAtDesc(Long pipelineId);
	List<PipelineRunEntity> findByStatus(String status);

	/** All pipeline runs that came from a single alarm via auto_check. We
	 *  serialise source_alarm_id into node_results JSON in
	 *  AutoCheckExecutor; PostgreSQL's jsonb operator extracts the field
	 *  for indexed lookup. Used by AlarmEnrichmentService so every bound
	 *  auto_check pipeline's output shows up in the alarm UI (the legacy
	 *  alarm.diagnostic_log_id only points at the last writer). */
	@Query(value = "SELECT * FROM pb_pipeline_runs " +
		"WHERE node_results::jsonb->>'source_alarm_id' = CAST(:alarmId AS text) " +
		"ORDER BY started_at DESC",
		nativeQuery = true)
	List<PipelineRunEntity> findAllByAlarmId(@Param("alarmId") Long alarmId);
}
