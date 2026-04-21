package com.aiops.api.domain.agent;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface AgentExperienceMemoryRepository extends JpaRepository<AgentExperienceMemoryEntity, Long> {
	List<AgentExperienceMemoryEntity> findByUserIdAndStatusOrderByLastUsedAtDesc(Long userId, String status);
}
