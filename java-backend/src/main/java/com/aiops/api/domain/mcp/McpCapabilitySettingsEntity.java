package com.aiops.api.domain.mcp;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.OffsetDateTime;

/**
 * MCP capability exposure override (V79, MCP-registry Phase 1). An OVERLAY on
 * the code-defined built-in tools, DB domain skills, and external MCPs — a row
 * exists only when IT admin has set a capability's public/private. Absence of a
 * row = default public (spec decision 4: current exposure stays open), so the
 * catalog LEFT JOINs this and treats "no row" as public.
 */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "mcp_capability_settings",
        indexes = @Index(name = "idx_mcp_cap_kind", columnList = "kind"))
public class McpCapabilitySettingsEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** tool name / skill slug / mcp name — unique across the registry. */
    @Column(name = "capability_key", nullable = false, unique = true, length = 200)
    private String capabilityKey;

    /** 'builtin' | 'domain_skill' | 'external' (spec decision 3 taxonomy). */
    @Column(name = "kind", nullable = false, length = 20)
    private String kind;

    /** Exposed to external cowork. private = internal agent only. */
    @Column(name = "is_public", nullable = false)
    private Boolean isPublic = Boolean.TRUE;

    @Column(name = "updated_by", length = 120)
    private String updatedBy;

    @UpdateTimestamp
    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt;
}
