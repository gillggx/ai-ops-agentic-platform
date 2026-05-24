package com.aiops.api.api.pipeline;

import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRunEntity;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

/**
 * HTTP-layer DTOs for {@link PipelineController}.
 *
 * <p>Extracted from {@code PipelineController.PipelineDtos} 2026-05-23 as part
 * of the Phase 12 Java OOP refactor — controller and the new
 * {@link PipelineService} both reference these types, so they live in their
 * own file rather than as a nested class inside the controller.
 */
public final class PipelineDtos {

	private PipelineDtos() {}

	public record Summary(Long id, String name, String description, String status,
	                      String pipelineKind, String version, Long createdBy,
	                      OffsetDateTime updatedAt) {}

	public record AutoCheckTriggerView(Long id, Long pipelineId, String eventType,
	                                   Object matchFilter, OffsetDateTime createdAt) {}

	public record Detail(Long id, String name, String description, String status,
	                     String pipelineKind, String version, String pipelineJson,
	                     String usageStats, String autoDoc, Long createdBy, Long approvedBy,
	                     Long parentId, OffsetDateTime createdAt, OffsetDateTime updatedAt,
	                     OffsetDateTime lockedAt, OffsetDateTime publishedAt,
	                     OffsetDateTime archivedAt) {}

	public record CreateRequest(@NotBlank String name, String description, String pipelineKind,
	                            String pipelineJson, String version) {}

	public record UpdateRequest(String name, String description, String pipelineKind,
	                            String pipelineJson, String autoDoc) {}

	public record TransitionRequest(@NotBlank String to, String notes) {}

	public record PublishRequest(Map<String, Object> reviewedDoc, String publishedBy) {}

	/**
	 * Phase D — body accepts a heterogeneous list:
	 * <pre>{@code
	 *   ["spc.ooc", "cpk.drop"]
	 * }</pre>
	 * OR
	 * <pre>{@code
	 *   [{event_type: "spc.ooc", match_filter: {severity: ["HIGH"]}}, ...]
	 * }</pre>
	 * Each element is either a String (legacy) or an Object with
	 * {@code {event_type, match_filter?}}. {@link PipelineService} normalises
	 * both shapes before writing trigger rows.
	 */
	public record PublishAutoCheckRequest(
			@NotNull
			@Size(min = 1, message = "event_types must contain at least one entry")
			List<Object> eventTypes) {}

	public record RunSummary(Long id, Long pipelineId, String pipelineVersion,
	                         String triggeredBy, String status,
	                         String nodeResults, String errorMessage,
	                         OffsetDateTime startedAt, OffsetDateTime finishedAt) {}

	public static RunSummary runSummaryOf(PipelineRunEntity e) {
		return new RunSummary(e.getId(), e.getPipelineId(), e.getPipelineVersion(),
				e.getTriggeredBy(), e.getStatus(),
				e.getNodeResults(), e.getErrorMessage(),
				e.getStartedAt(), e.getFinishedAt());
	}

	public static Summary summaryOf(PipelineEntity e) {
		return new Summary(e.getId(), e.getName(), e.getDescription(), e.getStatus(),
				e.getPipelineKind(), e.getVersion(), e.getCreatedBy(), e.getUpdatedAt());
	}

	public static Detail detailOf(PipelineEntity e) {
		return new Detail(e.getId(), e.getName(), e.getDescription(), e.getStatus(),
				e.getPipelineKind(), e.getVersion(), e.getPipelineJson(), e.getUsageStats(),
				e.getAutoDoc(), e.getCreatedBy(), e.getApprovedBy(), e.getParentId(),
				e.getCreatedAt(), e.getUpdatedAt(), e.getLockedAt(), e.getPublishedAt(),
				e.getArchivedAt());
	}
}
