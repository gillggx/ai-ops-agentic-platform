package com.aiops.api.domain.agent;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface AgentTaskRepository extends JpaRepository<AgentTaskEntity, String> {
	List<AgentTaskEntity> findTop10ByChatSessionIdOrderByCreatedAtDesc(String chatSessionId);

	/** ChatOps rail 最近運作 (2026-07-13)：本人跨對話的近期背景工作。 */
	List<AgentTaskEntity> findTop10ByUserIdOrderByCreatedAtDesc(Long userId);
}
