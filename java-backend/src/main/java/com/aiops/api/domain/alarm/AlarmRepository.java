package com.aiops.api.domain.alarm;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface AlarmRepository extends JpaRepository<AlarmEntity, Long> {
	List<AlarmEntity> findByStatusOrderByCreatedAtDesc(String status);
	List<AlarmEntity> findBySkillIdOrderByCreatedAtDesc(Long skillId);
}
