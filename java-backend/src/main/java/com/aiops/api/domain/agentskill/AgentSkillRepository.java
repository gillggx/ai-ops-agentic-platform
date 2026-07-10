package com.aiops.api.domain.agentskill;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface AgentSkillRepository extends JpaRepository<AgentSkillEntity, Long> {
	Optional<AgentSkillEntity> findByName(String name);
	List<AgentSkillEntity> findByEnabledTrueOrderByNameAsc();
	List<AgentSkillEntity> findAllByOrderByNameAsc();
}
