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
    // Legacy skillId-based queries (findBySkillId*, countNonTestSince,
    // findLastSystemTriggeredAt) removed in the 2026-06-29 sunset along with
    // the skill_runs.skill_id column (V68). v2 uses the *V2 variants below.

    /** Phase A (V67): same clock query keyed on skills_v2 id. */
    @Query("""
           SELECT MAX(r.triggeredAt) FROM SkillRunEntity r
           WHERE r.skillV2Id = :skillV2Id
             AND r.triggeredBy LIKE 'system_%'
           """)
    Optional<OffsetDateTime> findLastSystemTriggeredAtV2(@Param("skillV2Id") Long skillV2Id);

    // ─── V60 (2026-06-27) — Patrol Activity queries ─────────────────────

    /**
     * Patrol Activity main page query — fetch a page of skill_runs that match
     * the time window + optional skillId / cursor filters. Caller asks for
     * {@code limit + 1} rows to detect "has more".
     *
     * <p>{@code skillStage} and {@code eventType} are NOT in this query —
     * both live on/in {@link SkillDocumentEntity} (stage column / trigger_config
     * JSON), and pushing them into JPQL costs us either a fragile LIKE
     * (event_type) or runs into Hibernate's "bytea on null parameter to LOWER()"
     * type-inference quirk (stage). The service applies both filters in Java
     * after bulk-loading the per-page skills.
     */
    @Query("""
           SELECT r FROM SkillRunEntity r
           WHERE r.triggeredAt >= :since
             AND r.triggeredAt < :until
             AND r.skillV2Id IS NOT NULL
             AND (:skillId IS NULL OR r.skillV2Id = :skillId)
             AND (:cursor IS NULL OR r.id < :cursor)
           ORDER BY r.id DESC
           """)
    List<SkillRunEntity> findActivity(@Param("since") OffsetDateTime since,
                                       @Param("until") OffsetDateTime until,
                                       @Param("skillId") Long skillId,
                                       @Param("cursor") Long cursor,
                                       org.springframework.data.domain.Pageable pageable);

    /** Pageable-less overload — wraps the limit into a Pageable so service
     *  code doesn't import Spring Data types. */
    default List<SkillRunEntity> findActivity(OffsetDateTime since, OffsetDateTime until,
                                              Long skillId, Long cursor, int limit) {
        return findActivity(since, until, skillId, cursor,
                org.springframework.data.domain.PageRequest.of(0, limit));
    }

    /** Funnel: total v2 skill_runs in window. */
    @Query("""
           SELECT COUNT(r) FROM SkillRunEntity r
           WHERE r.triggeredAt >= :since AND r.triggeredAt < :until
             AND r.skillV2Id IS NOT NULL
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
             AND r.skill_v2_id IS NOT NULL
             AND r.step_results LIKE '%"status":"pass"%'
           """, nativeQuery = true)
    long countByTriggeredAtBetweenAndStepPassed(@Param("since") OffsetDateTime since,
                                                 @Param("until") OffsetDateTime until);

    /** Funnel: how many v2 runs got their alarm suppressed for the given reason. */
    @Query("""
           SELECT COUNT(r) FROM SkillRunEntity r
           WHERE r.triggeredAt >= :since AND r.triggeredAt < :until
             AND r.skillV2Id IS NOT NULL
             AND r.alarmSkippedReason = :reason
           """)
    long countByTriggeredAtBetweenAndAlarmSkippedReason(@Param("since") OffsetDateTime since,
                                                         @Param("until") OffsetDateTime until,
                                                         @Param("reason") String reason);
}
