package com.aiops.api.api.skill;

import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.common.PageResponse;
import com.aiops.api.domain.skill.ExecutionLogEntity;
import com.aiops.api.domain.skill.ExecutionLogRepository;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;

/** Read-only execution log view. All roles can observe, nobody can mutate. */
@RestController
@RequestMapping("/api/v1/execution-logs")
@PreAuthorize(Authorities.ANY_ROLE)
public class ExecutionLogController {

	private final ExecutionLogRepository repository;

	public ExecutionLogController(ExecutionLogRepository repository) {
		this.repository = repository;
	}

	/**
	 * V60 (2026-06-27): added {@code skillId}, {@code startedAfter},
	 * {@code startedBefore}, {@code status} filters so Patrol Activity side
	 * panel can drill into "all per-step rows for skill_run X" without
	 * pulling the whole 50-row page and filtering client-side.
	 */
	@GetMapping
	public ApiResponse<PageResponse<Dtos.Detail>> list(@RequestParam(defaultValue = "0") int page,
	                                                   @RequestParam(defaultValue = "50") int size,
	                                                   @RequestParam(required = false) Long skillId,
	                                                   @RequestParam(required = false) String startedAfter,
	                                                   @RequestParam(required = false) String startedBefore,
	                                                   @RequestParam(required = false) String status) {
		int safeSize = Math.min(Math.max(size, 1), 500);
		var pageable = PageRequest.of(page, safeSize, Sort.by(Sort.Direction.DESC, "startedAt"));

		OffsetDateTime after = parseIsoOrNull(startedAfter);
		OffsetDateTime before = parseIsoOrNull(startedBefore);
		String safeStatus = (status == null || status.isBlank()) ? null : status;

		boolean anyFilter = skillId != null || after != null || before != null || safeStatus != null;
		Page<ExecutionLogEntity> src = anyFilter
				? repository.findFiltered(skillId, after, before, safeStatus, pageable)
				: repository.findAll(pageable);
		return ApiResponse.ok(PageResponse.of(src, Dtos::of));
	}

	private static OffsetDateTime parseIsoOrNull(String raw) {
		if (raw == null || raw.isBlank()) return null;
		try {
			return OffsetDateTime.parse(raw);
		} catch (DateTimeParseException e) {
			return null;
		}
	}

	@GetMapping("/{id}")
	public ApiResponse<Dtos.Detail> get(@PathVariable Long id) {
		return ApiResponse.ok(Dtos.of(repository.findById(id)
				.orElseThrow(() -> ApiException.notFound("execution log"))));
	}

	public static final class Dtos {

		public record Detail(Long id, Long skillId, Long autoPatrolId, Long scriptVersionId,
		                     Long cronJobId, String triggeredBy, String eventContext, String status,
		                     String llmReadableData, String actionDispatched, String errorMessage,
		                     java.time.OffsetDateTime startedAt, java.time.OffsetDateTime finishedAt,
		                     Long durationMs) {}

		static Detail of(ExecutionLogEntity e) {
			return new Detail(e.getId(), e.getSkillId(), e.getAutoPatrolId(), e.getScriptVersionId(),
					e.getCronJobId(), e.getTriggeredBy(), e.getEventContext(), e.getStatus(),
					e.getLlmReadableData(), e.getActionDispatched(), e.getErrorMessage(),
					e.getStartedAt(), e.getFinishedAt(), e.getDurationMs());
		}
	}
}
