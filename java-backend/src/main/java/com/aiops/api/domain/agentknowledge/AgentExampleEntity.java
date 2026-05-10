package com.aiops.api.domain.agentknowledge;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

/** Few-shot example pair. embedding is on input_text — retrieval finds
 *  the K most similar inputs to current user_message and surfaces those
 *  pairs as few-shot examples in the system prompt. */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "agent_examples",
        indexes = @Index(name = "ix_agent_examples_user_scope",
                columnList = "user_id, scope_type, scope_value"))
public class AgentExampleEntity {

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

    @Column(name = "input_text", nullable = false, columnDefinition = "text")
    private String inputText;

    @Column(name = "output_text", nullable = false, columnDefinition = "text")
    private String outputText;

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
