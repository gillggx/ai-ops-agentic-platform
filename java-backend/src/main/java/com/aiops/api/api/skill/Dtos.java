package com.aiops.api.api.skill;

import com.aiops.api.domain.skill.SkillDocumentEntity;
import jakarta.validation.constraints.NotBlank;

import java.time.OffsetDateTime;

/**
 * DTOs for /api/v1/skills/*. Wire format is SNAKE_CASE (per Java backend
 * convention; see feedback_jackson_snake_case_wire memory) — Jackson
 * config in JacksonConfig translates record fields to snake_case.
 */
final class Dtos {
    private Dtos() {}

    /** Library row — compact summary. */
    record Summary(
            Long id, String slug, String title, String version,
            String stage, String domain, String description,
            String status, String certifiedBy, Long authorUserId,
            String triggerConfig,   // JSON string — frontend parses
            String stats,            // JSON string
            OffsetDateTime updatedAt
    ) {}

    /** Playbook detail — includes steps + (Phase 11 v2) confirm_check. */
    record Detail(
            Long id, String slug, String title, String version,
            String stage, String domain, String description,
            String status, String certifiedBy, Long authorUserId,
            String triggerConfig,
            String steps,
            String testCases,
            String stats,
            String confirmCheck,        // Phase 11 v2 — JSON or null (no gate)
            OffsetDateTime createdAt, OffsetDateTime updatedAt
    ) {}

    record CreateRequest(
            @NotBlank String slug,
            @NotBlank String title,
            @NotBlank String stage,           // patrol | diagnose
            String domain,
            String description,
            String version,
            String triggerConfig,             // JSON string
            String steps                      // JSON string
    ) {}

    record UpdateRequest(
            String title,
            String stage,
            String status,                    // draft | stable
            String domain,
            String description,
            String certifiedBy,
            String version,
            String triggerConfig,
            String steps,
            String confirmCheck               // Phase 11 v2 — JSON, null clears
    ) {}

    static Summary summaryOf(SkillDocumentEntity e) {
        return new Summary(
                e.getId(), e.getSlug(), e.getTitle(), e.getVersion(),
                e.getStage(), e.getDomain(), e.getDescription(),
                e.getStatus(), e.getCertifiedBy(), e.getAuthorUserId(),
                e.getTriggerConfig(), e.getStats(),
                e.getUpdatedAt()
        );
    }

    static Detail detailOf(SkillDocumentEntity e) {
        return new Detail(
                e.getId(), e.getSlug(), e.getTitle(), e.getVersion(),
                e.getStage(), e.getDomain(), e.getDescription(),
                e.getStatus(), e.getCertifiedBy(), e.getAuthorUserId(),
                e.getTriggerConfig(), e.getSteps(), e.getTestCases(), e.getStats(),
                e.getConfirmCheck(),
                e.getCreatedAt(), e.getUpdatedAt()
        );
    }
}
