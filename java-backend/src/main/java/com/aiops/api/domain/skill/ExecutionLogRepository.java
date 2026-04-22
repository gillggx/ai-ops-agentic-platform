package com.aiops.api.domain.skill;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface ExecutionLogRepository extends JpaRepository<ExecutionLogEntity, Long> {
	List<ExecutionLogEntity> findBySkillIdOrderByStartedAtDesc(Long skillId);
	List<ExecutionLogEntity> findByAutoPatrolIdOrderByStartedAtDesc(Long autoPatrolId);

	// Bounded variants — avoid loading 40k+ rows into heap.
	List<ExecutionLogEntity> findBySkillIdOrderByStartedAtDesc(Long skillId, Pageable pageable);
	List<ExecutionLogEntity> findByAutoPatrolIdOrderByStartedAtDesc(Long autoPatrolId, Pageable pageable);
}
