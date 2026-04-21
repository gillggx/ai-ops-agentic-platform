package com.aiops.api.domain.pipeline;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface PublishedSkillRepository extends JpaRepository<PublishedSkillEntity, Long> {
	Optional<PublishedSkillEntity> findBySlug(String slug);
	Optional<PublishedSkillEntity> findByPipelineIdAndPipelineVersion(Long pipelineId, String pipelineVersion);
	List<PublishedSkillEntity> findByStatus(String status);
}
