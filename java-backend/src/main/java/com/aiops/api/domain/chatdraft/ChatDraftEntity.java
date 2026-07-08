package com.aiops.api.domain.chatdraft;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.OffsetDateTime;

/**
 * Chat 草稿暫存區 (2026-07-08, V78). A pipeline built in the chat panel is
 * auto-parked here (most-recent 10). Lightweight + independent of
 * {@code skills_v2}: no role / automation / parameterize until the user
 * "enables" it, at which point it graduates to a real Skill.
 *
 * <p>Eviction (in the service on insert): keep at most 10 per user; when
 * over, drop the OLDEST {@code marked=false} draft. Marked drafts are never
 * auto-evicted and survive "clear unmarked".
 */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "pb_chat_drafts",
        indexes = @Index(name = "ix_pb_chat_drafts_user", columnList = "user_id, created_at"))
public class ChatDraftEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "name", nullable = false, columnDefinition = "text")
    private String name = "";

    /** The user's original NL prompt (intent prefix stripped). */
    @Column(name = "nl", nullable = false, columnDefinition = "text")
    private String nl = "";

    /** The built pipeline JSON — source of truth for open / enable. */
    @Column(name = "pipeline_json", nullable = false, columnDefinition = "text")
    private String pipelineJson;

    /** Per-node output columns {node_id: [col,...]} for column-aware modify. */
    @Column(name = "columns_json", nullable = false, columnDefinition = "text")
    private String columnsJson = "{}";

    /** Thumbnail hint: spc_trend / bar / table / panel / pareto / chart. */
    @Column(name = "kind", nullable = false)
    private String kind = "";

    @Column(name = "node_count", nullable = false)
    private Integer nodeCount = 0;

    @Column(name = "edge_count", nullable = false)
    private Integer edgeCount = 0;

    /** Pinned — never auto-evicted, survives "clear unmarked". */
    @Column(name = "marked", nullable = false)
    private Boolean marked = Boolean.FALSE;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private OffsetDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt;
}
