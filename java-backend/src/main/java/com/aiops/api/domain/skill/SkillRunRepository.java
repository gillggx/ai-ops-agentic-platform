package com.aiops.api.domain.skill;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;

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

    /**
     * v6.1 (2026-05-20): used by java-scheduler SkillScheduleService to decide
     * whether a schedule-mode skill is "due" — compare now() against last
     * triggered_at WHERE triggered_by LIKE 'system_%'. Manual + test runs
     * are excluded so user intervention doesn't reset the schedule clock.
     */
    @Query("""
           SELECT MAX(r.triggeredAt) FROM SkillRunEntity r
           WHERE r.skillId = :skillId
             AND r.triggeredBy LIKE 'system_%'
           """)
    Optional<OffsetDateTime> findLastSystemTriggeredAt(@Param("skillId") Long skillId);
}
