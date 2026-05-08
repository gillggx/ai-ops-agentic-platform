package com.aiops.api.api.rules;

import com.aiops.api.domain.patrol.AutoPatrolEntity;

import java.time.OffsetDateTime;

/**
 * DTOs for /api/v1/rules. Kept inline (small surface, single-controller
 * scope). Mirrors the wire shape we want; AutoPatrolEntity has more
 * fields, but personal rules only expose this subset.
 */
public final class Dtos {

	private Dtos() {}

	public record CreateRuleRequest(
			String name,
			String description,
			String kind,                       // personal_briefing | weekly_report | saved_query | watch_rule
			String scheduleCron,               // e.g. "0 8 * * 1"
			Long pipelineId,                   // either pipeline_id OR pipeline_json
			String pipelineJson,
			String notificationChannels,       // JSON: [{"type":"in_app"}]
			String notificationTemplate
	) {}

	public record PatchRuleRequest(
			Boolean isActive,
			String scheduleCron,
			String notificationTemplate,
			String notificationChannels
	) {}

	public record RuleDto(
			Long id,
			String name,
			String description,
			String kind,
			String scheduleCron,
			Long pipelineId,
			Boolean isActive,
			String notificationChannels,
			String notificationTemplate,
			OffsetDateTime lastDispatchedAt,
			OffsetDateTime createdAt,
			Long createdBy
	) {}

	static RuleDto ruleOf(AutoPatrolEntity e) {
		return new RuleDto(
				e.getId(),
				e.getName(),
				e.getDescription(),
				e.getKind(),
				e.getCronExpr(),
				e.getPipelineId(),
				e.getIsActive(),
				e.getNotificationChannels(),
				e.getNotificationTemplate(),
				e.getLastDispatchedAt(),
				e.getCreatedAt(),
				e.getCreatedBy()
		);
	}
}
