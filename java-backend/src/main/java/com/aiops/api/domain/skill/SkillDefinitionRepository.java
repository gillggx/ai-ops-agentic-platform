package com.aiops.api.domain.skill;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface SkillDefinitionRepository extends JpaRepository<SkillDefinitionEntity, Long> {
	Optional<SkillDefinitionEntity> findByName(String name);
	List<SkillDefinitionEntity> findBySource(String source);
	List<SkillDefinitionEntity> findByVisibility(String visibility);
	List<SkillDefinitionEntity> findByIsActiveTrue();
}
