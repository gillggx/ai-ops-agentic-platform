package com.aiops.api.domain.patrol;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface AutoPatrolRepository extends JpaRepository<AutoPatrolEntity, Long> {
	List<AutoPatrolEntity> findByIsActiveTrue();
	List<AutoPatrolEntity> findByTriggerMode(String triggerMode);
	List<AutoPatrolEntity> findByPipelineId(Long pipelineId);
}
