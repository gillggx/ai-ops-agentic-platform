package com.aiops.api.domain.agentepisode;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

/**
 * One structured behavioural event in an episode (V69). Emitted by
 * deterministic graph code only (never the LLM); high-volume + lean —
 * no audit columns, retention 90 days (pruned by a later job).
 *
 * <p>event_type taxonomy (spec §4.2): plan_proposed / plan_user_edited /
 * plan_confirmed / replan / phase_started / phase_done / block_picked /
 * param_reject_fix / doc_mismatch / verifier_reject / stuck_escalated /
 * repair_triggered / repair_outcome / llm_usage.
 */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "agent_steps")
public class AgentStepEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "episode_id", nullable = false)
    private Long episodeId;

    /** planner | builder | repair | system */
    @Column(name = "agent", length = 16, nullable = false)
    private String agent;

    @Column(name = "phase_id", length = 16)
    private String phaseId;

    @Column(name = "event_type", length = 40, nullable = false)
    private String eventType;

    /** JSON payload, shape defined per event_type. */
    @Column(name = "payload", columnDefinition = "text")
    private String payload;

    @Column(name = "input_tokens")
    private Integer inputTokens;

    @Column(name = "output_tokens")
    private Integer outputTokens;

    @Column(name = "cache_read")
    private Integer cacheRead;

    @Column(name = "latency_ms")
    private Integer latencyMs;

    @Column(name = "ts", nullable = false)
    private OffsetDateTime ts;
}
