package com.aiops.api.domain.pipeline;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface PipelineAutoCheckTriggerRepository extends JpaRepository<PipelineAutoCheckTriggerEntity, Long> {
	List<PipelineAutoCheckTriggerEntity> findByPipelineId(Long pipelineId);
	List<PipelineAutoCheckTriggerEntity> findByEventType(String eventType);
}
