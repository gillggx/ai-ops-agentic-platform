package com.aiops.api.domain.agent;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface AgentTaskRepository extends JpaRepository<AgentTaskEntity, String> {
	List<AgentTaskEntity> findTop10ByChatSessionIdOrderByCreatedAtDesc(String chatSessionId);
}
