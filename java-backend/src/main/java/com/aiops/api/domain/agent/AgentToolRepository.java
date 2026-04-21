package com.aiops.api.domain.agent;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface AgentToolRepository extends JpaRepository<AgentToolEntity, Long> {
	List<AgentToolEntity> findByUserIdOrderByUpdatedAtDesc(Long userId);
}
