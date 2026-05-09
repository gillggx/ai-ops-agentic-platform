package com.aiops.api.domain.skill;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface SkillDocumentRepository extends JpaRepository<SkillDocumentEntity, Long> {
    Optional<SkillDocumentEntity> findBySlug(String slug);
    List<SkillDocumentEntity> findByStage(String stage);
    List<SkillDocumentEntity> findByStatus(String status);
    List<SkillDocumentEntity> findByAuthorUserId(Long authorUserId);
    boolean existsBySlug(String slug);
}
