package com.aiops.api.domain.skill;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

/**
 * Phase 11 — Per-fire audit log for personal/user-defined rules.
 *
 * <p>Phase 9 didn't record per-fire history; the Skill Test modal's
 * Past event tab needs it for trigger.type=user replay.
 */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "personal_rule_fires",
        indexes = {
                @Index(name = "ix_personal_rule_fires_rule", columnList = "patrol_id, fired_at"),
        })
public class PersonalRuleFireEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "patrol_id", nullable = false)
    private Long patrolId;

    @Column(name = "fired_at", nullable = false)
    private OffsetDateTime firedAt = OffsetDateTime.now();

    @Column(name = "payload", nullable = false, columnDefinition = "text")
    private String payload = "{}";

    @Column(name = "inbox_id")
    private Long inboxId;
}
