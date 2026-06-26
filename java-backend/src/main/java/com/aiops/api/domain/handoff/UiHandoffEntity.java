package com.aiops.api.domain.handoff;

import com.aiops.api.domain.common.Auditable;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

/**
 * UI handoff — "cowork proposes, the human disposes in the real GUI" (V63).
 *
 * <p>The MCP server creates one of these instead of mutating directly; the
 * frontend resolves it (review a rule, or confirm a dangerous action). The
 * actual delete/disable/activate runs only from {@code HandoffService.resolve}
 * under the authenticated user — never from the MCP layer.
 *
 * <p>{@code id} is a non-guessable token assigned by the service (not generated
 * by the DB), so the launch URL {@code /handoff/<id>} is unguessable.
 */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "ui_handoffs",
        indexes = {
                @Index(name = "ix_ui_handoffs_status", columnList = "status"),
                @Index(name = "ix_ui_handoffs_expires_at", columnList = "expires_at"),
        })
public class UiHandoffEntity extends Auditable {

    @Id
    @Column(name = "id", length = 40, nullable = false)
    private String id;

    /** review_rule | confirm_delete | confirm_disable | confirm_activate | view_detail */
    @Column(name = "kind", length = 40, nullable = false)
    private String kind;

    /** skill slug or pipeline id */
    @Column(name = "target_ref", length = 180)
    private String targetRef;

    /** delete | disable | activate — for confirm_* kinds */
    @Column(name = "action", length = 40)
    private String action;

    /** JSON: impact / summary the modal renders */
    @Column(name = "payload", columnDefinition = "text")
    private String payload;

    /** pending | resolved | cancelled | expired */
    @Column(name = "status", length = 20, nullable = false)
    private String status = "pending";

    @Column(name = "requested_by", length = 80)
    private String requestedBy;

    @Column(name = "resolved_by")
    private Long resolvedBy;

    @Column(name = "resolved_at", columnDefinition = "timestamp with time zone")
    private OffsetDateTime resolvedAt;

    @Column(name = "expires_at", columnDefinition = "timestamp with time zone", nullable = false)
    private OffsetDateTime expiresAt;
}
