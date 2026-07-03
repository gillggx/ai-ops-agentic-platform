package com.aiops.api.domain.supervisor;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.time.OffsetDateTime;

/**
 * One Supervisor curation proposal (V72; Phase 5).
 *
 * <p>PROPOSE-ONLY by design (2026-07-03 pollution incident): the Supervisor
 * never mutates memories directly — a human approves in /supervisor and only
 * then does {@code SupervisorCurationService} commit the change.
 */
@Getter
@Setter
@Entity
@Table(name = "supervisor_actions")
public class SupervisorActionEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** MERGE | CORRECT | PRUNE | PROMOTE | DOC_REVISE */
    @Column(name = "action_type", length = 16, nullable = false)
    private String actionType;

    /** JSON array of targeted agent_knowledge / block_doc_memo ids. */
    @Column(name = "target_ids", columnDefinition = "text")
    private String targetIds;

    /** Full structured proposal JSON (per-type shape). */
    @Column(name = "proposal", columnDefinition = "text", nullable = false)
    private String proposal;

    /** One-line human-readable rationale from the proposer. */
    @Column(name = "rationale", columnDefinition = "text")
    private String rationale;

    /** proposed | approved | rejected */
    @Column(name = "status", length = 12, nullable = false)
    private String status = "proposed";

    /** Provenance of the proposing run (model, counts) — JSON. */
    @Column(name = "proposer_meta", columnDefinition = "text")
    private String proposerMeta;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private OffsetDateTime createdAt;

    @Column(name = "reviewed_by")
    private Long reviewedBy;

    @Column(name = "reviewed_at")
    private OffsetDateTime reviewedAt;

    /** What actually happened on approve (created row id, etc.) — JSON. */
    @Column(name = "commit_result", columnDefinition = "text")
    private String commitResult;
}
