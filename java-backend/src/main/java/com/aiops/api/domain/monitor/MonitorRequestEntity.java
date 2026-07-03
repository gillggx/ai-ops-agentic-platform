package com.aiops.api.domain.monitor;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.time.OffsetDateTime;

/**
 * One monitor improvement request (V73; Phase 6 option A: self-health).
 * The monitor watches OUR agents' episode metrics and files requests; a human
 * approves before anything drives the Planner.
 */
@Getter
@Setter
@Entity
@Table(name = "monitor_requests")
public class MonitorRequestEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** DOC_GAP | DIVERGENCE | REPAIR_HANDOVER */
    @Column(name = "kind", length = 20, nullable = false)
    private String kind;

    /** Block id for DOC_GAP; metric key otherwise. */
    @Column(name = "subject", length = 120, nullable = false)
    private String subject;

    /** Measured evidence JSON: {metric, value, threshold, window_days}. */
    @Column(name = "evidence", columnDefinition = "text", nullable = false)
    private String evidence;

    /** Prepared instruction a human can launch at the Planner after approval. */
    @Column(name = "suggested_instruction", columnDefinition = "text")
    private String suggestedInstruction;

    /** open | approved | dismissed */
    @Column(name = "status", length = 12, nullable = false)
    private String status = "open";

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private OffsetDateTime createdAt;

    @Column(name = "reviewed_by")
    private Long reviewedBy;

    @Column(name = "reviewed_at")
    private OffsetDateTime reviewedAt;
}
