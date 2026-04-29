package com.aiops.api.domain.pipeline;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface PipelineAutoCheckTriggerRepository extends JpaRepository<PipelineAutoCheckTriggerEntity, Long> {
	List<PipelineAutoCheckTriggerEntity> findByPipelineId(Long pipelineId);
	List<PipelineAutoCheckTriggerEntity> findByEventType(String eventType);

	/** Bulk delete via JPQL — single DELETE statement, no entity hydration. Used by
	 *  publish-auto-check to atomically replace event-type bindings for a pipeline. */
	@Modifying
	@Query("DELETE FROM PipelineAutoCheckTriggerEntity t WHERE t.pipelineId = :pipelineId")
	int deleteByPipelineId(@Param("pipelineId") Long pipelineId);
}
