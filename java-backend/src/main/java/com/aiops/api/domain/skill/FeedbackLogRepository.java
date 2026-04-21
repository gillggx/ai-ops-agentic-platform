package com.aiops.api.domain.skill;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface FeedbackLogRepository extends JpaRepository<FeedbackLogEntity, Long> {
	List<FeedbackLogEntity> findByTargetTypeAndTargetIdOrderByCreatedAtDesc(String targetType, Long targetId);
}
