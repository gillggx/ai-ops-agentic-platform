package com.aiops.api.domain.agentknowledge;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface AgentDirectiveFireRepository extends JpaRepository<AgentDirectiveFireEntity, Long> {
    List<AgentDirectiveFireEntity> findByDirectiveIdOrderByFiredAtDesc(Long directiveId, Pageable pageable);

    long countByDirectiveId(Long directiveId);
}
