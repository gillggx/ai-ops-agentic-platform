package com.aiops.api.domain.agentknowledge;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface AgentLexiconRepository extends JpaRepository<AgentLexiconEntity, Long> {
    List<AgentLexiconEntity> findByUserIdOrderByUsesDescTermAsc(Long userId);

    Optional<AgentLexiconEntity> findByUserIdAndTerm(Long userId, String term);
}
