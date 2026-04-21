package com.aiops.api.domain.skill;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface RoutineCheckRepository extends JpaRepository<RoutineCheckEntity, Long> {
	List<RoutineCheckEntity> findBySkillId(Long skillId);
	List<RoutineCheckEntity> findByIsActiveTrue();
}
