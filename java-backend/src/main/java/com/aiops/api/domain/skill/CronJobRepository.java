package com.aiops.api.domain.skill;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface CronJobRepository extends JpaRepository<CronJobEntity, Long> {
	List<CronJobEntity> findBySkillId(Long skillId);
	List<CronJobEntity> findByStatus(String status);
}
