package com.aiops.api.domain.agentknowledge;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

/** RAG-retrievable domain fact. embedding (1024-dim) is computed by the
 *  sidecar when the row is created/updated and used for cosine similarity
 *  search at retrieval time. */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "agent_knowledge",
        indexes = @Index(name = "ix_agent_knowledge_user_scope",
                columnList = "user_id, scope_type, scope_value, active"))
public class AgentKnowledgeEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "scope_type", nullable = false, length = 20)
    private String scopeType;

    @Column(name = "scope_value", length = 120)
    private String scopeValue;

    @Column(name = "title", nullable = false, length = 200)
    private String title;

    @Column(name = "body", nullable = false, columnDefinition = "text")
    private String body;

    @Column(name = "priority", nullable = false, length = 10)
    private String priority = "med";

    /** V58: which agent layer consumes this entry — 'plan' (shapes intent /
     *  phase decomposition), 'execute' (guides block / param choice at
     *  commit_pick / construct), or 'both'. Drives layer-filtered retrieval
     *  so block-choice knowledge reaches the layer that actually picks blocks. */
    @Column(name = "applies_to", nullable = false, length = 10)
    private String appliesTo = "both";

    /** V70: 6-class memory taxonomy (domain|preference|presentation|
     *  correction|episodic|procedure). NULL = legacy-unclassified (pre-V70
     *  rows) — retrieval treats NULL exactly as before, zero regression.
     *  Agent-written rows (memory layer W1-W3) always set it. */
    @Column(name = "memo_class", length = 16)
    private String memoClass;

    /** V71: which agent wrote this row — planner | builder | repair | human.
     *  NULL = legacy (pre-V71) agent_fast rows we don't retro-guess. Builder
     *  memories live in block_doc_memos, not here. */
    @Column(name = "written_by", length = 12)
    private String writtenBy;

    /** V58: bypass RAG — inject unconditionally. Reserved for the few
     *  first-principle rules that MUST land regardless of multilingual recall
     *  (SPC/APC/FDC level, "視覺化必含 chart block"). Everything else is RAG-only. */
    @Column(name = "always_on", nullable = false)
    private Boolean alwaysOn = false;

    @Column(name = "active", nullable = false)
    private Boolean active = true;

    /** V75 lifecycle: draft | active | stale | archived. Retrieval paths
     *  (searchByEmbedding / highPriorityKnowledge) only serve 'active'.
     *  ON_DUTY-created rows and W3 repair corrections land as 'draft' until
     *  a PE / IT_ADMIN approves. */
    @Column(name = "status", nullable = false, length = 12)
    private String status = "active";

    /** V75 C1 subject index: block | tool | skill | request_class | general. */
    @Column(name = "subject_kind", length = 16)
    private String subjectKind;

    @Column(name = "subject_id", length = 80)
    private String subjectId;

    /** V75 C2: annual-review due date for domain/procedure rows. */
    @Column(name = "review_at")
    private OffsetDateTime reviewAt;

    @Column(name = "expires_at")
    private OffsetDateTime expiresAt;

    /** V75: id of the agent_knowledge row that replaced this one. */
    @Column(name = "superseded_by")
    private Long supersededBy;

    @Column(name = "source", nullable = false, length = 20)
    private String source = "manual";

    /** pgvector(1024). insertable/updatable=false because JPA binds String
     *  as VARCHAR, which PostgreSQL refuses to implicitly cast to vector
     *  (see AgentKnowledgeRepository.updateEmbedding). All writes go through
     *  native SQL (sidecar's _backfill_embeddings + repo.updateEmbedding /
     *  clearEmbedding). JPA still SELECTs this column for reads via the
     *  field reflection, so {@code getEmbedding()} returns the current value. */
    @Column(name = "embedding", columnDefinition = "vector(1024)",
            insertable = false, updatable = false)
    private String embedding;

    @Column(name = "uses", nullable = false)
    private Integer uses = 0;

    @Column(name = "last_used_at")
    private OffsetDateTime lastUsedAt;

    @Column(name = "created_at", nullable = false)
    private OffsetDateTime createdAt = OffsetDateTime.now();

    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt = OffsetDateTime.now();
}
