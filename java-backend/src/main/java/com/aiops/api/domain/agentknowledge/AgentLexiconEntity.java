package com.aiops.api.domain.agentknowledge;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

/** User's jargon → standard term mapping. The sidecar uses this to
 *  transparently rewrite user_message ("打點" → "打點 (= OOC excursion)")
 *  before LLM consumption, so the LLM sees both forms. */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "agent_lexicon",
        uniqueConstraints = @UniqueConstraint(columnNames = {"user_id", "term"}),
        indexes = @Index(name = "ix_agent_lexicon_user", columnList = "user_id"))
public class AgentLexiconEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "term", nullable = false, length = 80)
    private String term;

    @Column(name = "standard", nullable = false, length = 120)
    private String standard;

    @Column(name = "note", columnDefinition = "text")
    private String note;

    @Column(name = "uses", nullable = false)
    private Integer uses = 0;

    @Column(name = "created_at", nullable = false)
    private OffsetDateTime createdAt = OffsetDateTime.now();

    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt = OffsetDateTime.now();
}
