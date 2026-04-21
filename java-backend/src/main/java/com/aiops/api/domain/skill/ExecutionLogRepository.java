package com.aiops.api.domain.skill;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface ExecutionLogRepository extends JpaRepository<ExecutionLogEntity, Long> {
	List<ExecutionLogEntity> findBySkillIdOrderByStartedAtDesc(Long skillId);
	List<ExecutionLogEntity> findByAutoPatrolIdOrderByStartedAtDesc(Long autoPatrolId);
}
