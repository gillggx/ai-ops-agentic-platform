package com.aiops.api.domain.skill;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface ScriptVersionRepository extends JpaRepository<ScriptVersionEntity, Long> {
	List<ScriptVersionEntity> findBySkillIdOrderByVersionDesc(Long skillId);
}
