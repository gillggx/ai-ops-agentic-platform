package com.aiops.api.domain.skillv2;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface SkillV2Repository extends JpaRepository<SkillV2Entity, Long> {
	Optional<SkillV2Entity> findBySlug(String slug);
	List<SkillV2Entity> findByRole(String role);
	List<SkillV2Entity> findByStatusOrderByNameAsc(String status);
}
