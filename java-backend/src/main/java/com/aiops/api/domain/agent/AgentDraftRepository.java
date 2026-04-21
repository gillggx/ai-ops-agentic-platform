package com.aiops.api.domain.agent;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface AgentDraftRepository extends JpaRepository<AgentDraftEntity, String> {
	List<AgentDraftEntity> findByUserIdOrderByCreatedAtDesc(Long userId);
	List<AgentDraftEntity> findByUserIdAndStatus(Long userId, String status);
}
