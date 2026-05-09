package com.aiops.api.domain.skill;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

/**
 * Phase 11 — One row per Skill execution.
 *
 * <p>{@code is_test=true} marks sandbox runs (test modal): they don't dispatch
 * notifications and are excluded from {@link SkillDocumentEntity#getStats()}.
 */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "skill_runs",
        indexes = {
                @Index(name = "ix_skill_runs_skill", columnList = "skill_id, triggered_at"),
                @Index(name = "ix_skill_runs_test", columnList = "skill_id, is_test, triggered_at"),
        })
public class SkillRunEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "skill_id", nullable = false)
    private Long skillId;

    @Column(name = "triggered_at", nullable = false)
    private OffsetDateTime triggeredAt = OffsetDateTime.now();

    /** event:OCAP_TRIGGERED | cron | user_test */
    @Column(name = "triggered_by", nullable = false, length = 40)
    private String triggeredBy;

    @Column(name = "trigger_payload", nullable = false, columnDefinition = "text")
    private String triggerPayload = "{}";

    @Column(name = "is_test", nullable = false)
    private Boolean isTest = Boolean.FALSE;

    /** running | completed | failed | cancelled */
    @Column(name = "status", nullable = false, length = 20)
    private String status = "running";

    /**
     * JSON array — per-step result snapshots:
     * [{step_id, pipeline_run_id, status, value, note, duration_ms}]
     */
    @Column(name = "step_results", nullable = false, columnDefinition = "text")
    private String stepResults = "[]";

    @Column(name = "duration_ms")
    private Integer durationMs;

    @Column(name = "finished_at")
    private OffsetDateTime finishedAt;
}
