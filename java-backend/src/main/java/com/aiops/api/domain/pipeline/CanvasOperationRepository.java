package com.aiops.api.domain.pipeline;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface CanvasOperationRepository extends JpaRepository<CanvasOperationEntity, Long> {
	List<CanvasOperationEntity> findByPipelineIdOrderByCreatedAtAsc(Long pipelineId);
}
