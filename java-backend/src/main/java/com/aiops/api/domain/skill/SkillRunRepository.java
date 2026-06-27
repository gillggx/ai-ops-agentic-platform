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

    // ─── V60 (2026-06-27) — Patrol Activity queries ─────────────────────

    /**
     * Patrol Activity main page query — fetch a page of skill_runs that match
     * the time window + optional filters. Cursor is the last seen run id;
     * pass NULL for the first page. Caller asks for {@code limit + 1} rows to
     * detect "has more". skillStage is joined from skill_documents via an
     * EXISTS subquery so we don't need an entity-level FK.
     *
     * <p>event_type filtering is done in service-layer code because it lives
     * in trigger_config JSON and can't be queried efficiently in JPQL.
     */
    @Query("""
           SELECT r FROM SkillRunEntity r
           WHERE r.triggeredAt >= :since
             AND r.triggeredAt < :until
             AND (:skillId IS NULL OR r.skillId = :skillId)
             AND (:cursor IS NULL OR r.id < :cursor)
             AND (:stage IS NULL OR EXISTS (
                   SELECT 1 FROM SkillDocumentEntity s
                   WHERE s.id = r.skillId AND LOWER(s.stage) = LOWER(:stage)))
           ORDER BY r.id DESC
           """)
    List<SkillRunEntity> findActivity(@Param("since") OffsetDateTime since,
                                       @Param("until") OffsetDateTime until,
                                       @Param("skillId") Long skillId,
                                       @Param("stage") String stage,
                                       @Param("cursor") Long cursor,
                                       org.springframework.data.domain.Pageable pageable);

    /** Pageable-less overload — wraps the limit into a Pageable so service
     *  code doesn't import Spring Data types. */
    default List<SkillRunEntity> findActivity(OffsetDateTime since, OffsetDateTime until,
                                              Long skillId, String stage,
                                              Long cursor, int limit) {
        return findActivity(since, until, skillId, stage, cursor,
                org.springframework.data.domain.PageRequest.of(0, limit));
    }

    /** Funnel: total skill_runs in window. */
    @Query("""
           SELECT COUNT(r) FROM SkillRunEntity r
           WHERE r.triggeredAt >= :since AND r.triggeredAt < :until
           """)
    long countByTriggeredAtBetween(@Param("since") OffsetDateTime since,
                                    @Param("until") OffsetDateTime until);

    /**
     * Funnel: skill_runs whose step_results JSON has at least one
     * {@code status:"pass"} entry. Plain SQL LIKE is intentional — step_results
     * is TEXT (not jsonb) on this schema, and adding a functional index for a
     * single-call funnel isn't worth the migration. Match is anchored to
     * {@code "status":"pass"} including JSON quotes so a free-text "pass" in
     * a note field won't false-positive.
     */
    @Query(value = """
           SELECT COUNT(*) FROM skill_runs r
           WHERE r.triggered_at >= :since AND r.triggered_at < :until
             AND r.step_results LIKE '%"status":"pass"%'
           """, nativeQuery = true)
    long countByTriggeredAtBetweenAndStepPassed(@Param("since") OffsetDateTime since,
                                                 @Param("until") OffsetDateTime until);

    /** Funnel: how many runs got their alarm suppressed for the given reason. */
    @Query("""
           SELECT COUNT(r) FROM SkillRunEntity r
           WHERE r.triggeredAt >= :since AND r.triggeredAt < :until
             AND r.alarmSkippedReason = :reason
           """)
    long countByTriggeredAtBetweenAndAlarmSkippedReason(@Param("since") OffsetDateTime since,
                                                         @Param("until") OffsetDateTime until,
                                                         @Param("reason") String reason);
}
