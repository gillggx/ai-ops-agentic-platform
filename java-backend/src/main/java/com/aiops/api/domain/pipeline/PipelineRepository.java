package com.aiops.api.domain.pipeline;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface PipelineRepository extends JpaRepository<PipelineEntity, Long> {
	List<PipelineEntity> findByStatus(String status);
	List<PipelineEntity> findByCreatedBy(Long createdBy);
}
