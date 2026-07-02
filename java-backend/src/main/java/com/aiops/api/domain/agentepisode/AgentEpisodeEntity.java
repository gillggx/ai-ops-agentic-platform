package com.aiops.api.domain.agentepisode;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

/**
 * One build = one episode (V69). Keyed by the sidecar session_id so the
 * recorder can idempotently upsert across batched flushes. The Supervisor
 * tuning loop reads these across builds; the raw /tmp llm_calls trace stays
 * the debug drill-down layer ({@code traceFile} cross-ref).
 *
 * <p>Spec: docs/MULTI_AGENT_OBSERVABILITY_SPEC.md §4.1.
 */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "agent_episodes")
public class AgentEpisodeEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** Sidecar session_id — unique, idempotency key for recorder flushes. */
    @Column(name = "episode_key", length = 64, nullable = false, unique = true)
    private String episodeKey;

    @Column(name = "user_id")
    private Long userId;

    @Column(name = "instruction", columnDefinition = "text", nullable = false)
    private String instruction = "";

    /** Final phases JSON (after user edits at the confirm gate). */
    @Column(name = "plan_json", columnDefinition = "text")
    private String planJson;

    /** JSON: {ok, verifier_passed, ...} — the system's own view of success. */
    @Column(name = "self_assessment", columnDefinition = "text")
    private String selfAssessment;

    /** JSON list: [{stage, sentiment, text, ts}] — plan edits + post-delivery. */
    @Column(name = "user_feedback", columnDefinition = "text")
    private String userFeedback;

    /** Derived: self says ok BUT user rejected — the gold learning signal. */
    @Column(name = "divergence", nullable = false)
    private boolean divergence = false;

    /** Per-agent token/cache/latency rollup JSON. */
    @Column(name = "cost_json", columnDefinition = "text")
    private String costJson;

    /** running | finished | failed | handover | partial */
    @Column(name = "status", length = 24, nullable = false)
    private String status = "running";

    /** Raw builder-trace path for debug drill-down. */
    @Column(name = "trace_file", columnDefinition = "text")
    private String traceFile;

    @Column(name = "started_at", nullable = false)
    private OffsetDateTime startedAt;

    @Column(name = "finished_at")
    private OffsetDateTime finishedAt;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private OffsetDateTime createdAt;

    @Column(name = "updated_at", nullable = false, insertable = false, updatable = false)
    private OffsetDateTime updatedAt;
}
