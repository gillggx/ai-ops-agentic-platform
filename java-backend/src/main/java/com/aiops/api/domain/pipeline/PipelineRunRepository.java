package com.aiops.api.domain.pipeline;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface PipelineRunRepository extends JpaRepository<PipelineRunEntity, Long> {
	List<PipelineRunEntity> findByPipelineIdOrderByStartedAtDesc(Long pipelineId);
	List<PipelineRunEntity> findByStatus(String status);
}
