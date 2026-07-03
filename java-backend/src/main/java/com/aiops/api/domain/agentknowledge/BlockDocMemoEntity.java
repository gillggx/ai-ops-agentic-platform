package com.aiops.api.domain.agentknowledge;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

/**
 * Builder's "sticky note next to the block doc" (V70). A REVIEW QUEUE:
 * memos are candidates distilled from verifier rejects — they never mutate
 * block_docs directly (single-source-of-truth). Supervisor's DOC_GAP
 * aggregates pending memos per block; a human promotes/discards.
 *
 * <p>Design: AGENT_HARNESS_DESIGN.html §10; spec MULTI_AGENT_MEMORY_SPEC §3.1.
 */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "block_doc_memos")
public class BlockDocMemoEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "block_id", length = 100, nullable = false)
    private String blockId;

    @Column(name = "param", length = 100)
    private String param;

    /** Deterministic summary (E1 — no LLM in v1). */
    @Column(name = "memo", columnDefinition = "text", nullable = false)
    private String memo;

    /** Reject payload(s) JSON — lets the reviewer see the raw evidence. */
    @Column(name = "verdict_context", columnDefinition = "text")
    private String verdictContext;

    @Column(name = "from_episode", length = 64)
    private String fromEpisode;

    /** pending | promoted | discarded */
    @Column(name = "status", length = 16, nullable = false)
    private String status = "pending";

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private OffsetDateTime createdAt;

    @Column(name = "reviewed_by")
    private Long reviewedBy;

    @Column(name = "reviewed_at")
    private OffsetDateTime reviewedAt;
}
