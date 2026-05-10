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

    @Column(name = "active", nullable = false)
    private Boolean active = true;

    @Column(name = "source", nullable = false, length = 20)
    private String source = "manual";

    /** pgvector(1024). Stored as text in JPA — direct vector ops happen
     *  in native queries (see AgentKnowledgeRepository#searchByEmbedding). */
    @Column(name = "embedding", columnDefinition = "vector(1024)")
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
