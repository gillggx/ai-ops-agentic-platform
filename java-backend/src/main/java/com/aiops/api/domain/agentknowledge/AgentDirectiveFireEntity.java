package com.aiops.api.domain.agentknowledge;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

/** Audit log: each time a directive is included in the agent's prompt. */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "agent_directive_fires",
        indexes = {
                @Index(name = "ix_directive_fires_directive",
                        columnList = "directive_id, fired_at"),
        })
public class AgentDirectiveFireEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "directive_id", nullable = false)
    private Long directiveId;

    @Column(name = "fired_at", nullable = false)
    private OffsetDateTime firedAt = OffsetDateTime.now();

    @Column(name = "session_id", length = 64)
    private String sessionId;

    @Column(name = "context", length = 200)
    private String context;
}
