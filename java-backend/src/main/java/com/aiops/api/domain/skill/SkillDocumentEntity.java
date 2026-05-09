package com.aiops.api.domain.skill;

import com.aiops.api.domain.common.Auditable;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

/**
 * Phase 11 — Skill as Knowledge Document.
 *
 * <p>The unifying abstraction over the four pre-existing trigger paths
 * (auto_patrols / pipeline_auto_check_triggers / personal-rule kind /
 * chat-invokable skill_definitions). A Skill carries:
 * <ul>
 *   <li>Lifecycle stage — patrol (continuous watch) | diagnose (root-cause)</li>
 *   <li>trigger_config (jsonb) — discriminated union: system | user | schedule</li>
 *   <li>steps (jsonb) — ordered list of {text, pipeline_id, suggested_actions}</li>
 * </ul>
 *
 * <p>Stored as TEXT (JSON-as-text, matching repo convention for Postgres jsonb
 * columns we don't want JPA to overinterpret).
 */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "skill_documents",
        indexes = {
                @Index(name = "ix_skill_documents_stage", columnList = "stage"),
                @Index(name = "ix_skill_documents_status", columnList = "status"),
                @Index(name = "ix_skill_documents_author", columnList = "author_user_id"),
        })
public class SkillDocumentEntity extends Auditable {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "slug", nullable = false, length = 120, unique = true)
    private String slug;

    @Column(name = "title", nullable = false, length = 200)
    private String title;

    @Column(name = "version", nullable = false, length = 20)
    private String version = "0.1";

    /** patrol | diagnose */
    @Column(name = "stage", nullable = false, length = 20)
    private String stage;

    @Column(name = "domain", nullable = false, length = 80)
    private String domain = "";

    @Column(name = "description", nullable = false, columnDefinition = "text")
    private String description = "";

    @Column(name = "author_user_id")
    private Long authorUserId;

    @Column(name = "certified_by", length = 120)
    private String certifiedBy;

    /** draft | stable */
    @Column(name = "status", nullable = false, length = 20)
    private String status = "draft";

    /** JSON discriminated union — see Phase 11 spec §2-1. */
    @Column(name = "trigger_config", nullable = false, columnDefinition = "text")
    private String triggerConfig = "{}";

    /**
     * JSON ordered array — each step has plain-language text + pipeline_id +
     * author-written suggested_actions. See migration V22 for shape.
     */
    @Column(name = "steps", nullable = false, columnDefinition = "text")
    private String steps = "[]";

    /** JSON array — Phase 11-E (deferred); empty in 11-A. */
    @Column(name = "test_cases", nullable = false, columnDefinition = "text")
    private String testCases = "[]";

    /**
     * JSON — denormalized counters refreshed by SkillRunner / nightly job.
     * Shape: {rating_avg, runs_total, runs_30d, last_run_at}.
     */
    @Column(name = "stats", nullable = false, columnDefinition = "text")
    private String stats = "{}";
}
