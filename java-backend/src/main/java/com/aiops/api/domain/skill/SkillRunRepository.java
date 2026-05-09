package com.aiops.api.domain.skill;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.OffsetDateTime;
import java.util.List;

@Repository
public interface SkillRunRepository extends JpaRepository<SkillRunEntity, Long> {
    List<SkillRunEntity> findBySkillIdOrderByTriggeredAtDesc(Long skillId);

    List<SkillRunEntity> findBySkillIdAndIsTestOrderByTriggeredAtDesc(Long skillId, Boolean isTest);

    @Query("""
           SELECT COUNT(r) FROM SkillRunEntity r
           WHERE r.skillId = :skillId
             AND r.isTest = false
             AND r.triggeredAt >= :since
           """)
    long countNonTestSince(@Param("skillId") Long skillId, @Param("since") OffsetDateTime since);
}
