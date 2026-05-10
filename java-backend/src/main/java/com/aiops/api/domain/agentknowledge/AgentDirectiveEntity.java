package com.aiops.api.domain.agentknowledge;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

/**
 * Always-on prompt directive that the agent's context_loader prepends to
 * the system prompt when scope matches.
 *
 * <p>2026-05-11: see V32 migration. Naming uses "directives" to avoid
 * clash with existing /api/v1/rules (auto_patrols-based scheduled
 * pipelines).
 */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "agent_directives",
        indexes = {
                @Index(name = "ix_agent_directives_user_scope",
                        columnList = "user_id, scope_type, scope_value, active"),
        })
public class AgentDirectiveEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "scope_type", nullable = false, length = 20)
    private String scopeType;          // global | skill | tool | recipe

    @Column(name = "scope_value", length = 120)
    private String scopeValue;         // null when scope_type=global

    @Column(name = "title", nullable = false, length = 200)
    private String title;

    @Column(name = "body", nullable = false, columnDefinition = "text")
    private String body;

    @Column(name = "priority", nullable = false, length = 10)
    private String priority = "med";   // high | med | low

    @Column(name = "active", nullable = false)
    private Boolean active = true;

    @Column(name = "source", nullable = false, length = 20)
    private String source = "manual";  // manual | auto-promoted

    @Column(name = "created_at", nullable = false)
    private OffsetDateTime createdAt = OffsetDateTime.now();

    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt = OffsetDateTime.now();
}
