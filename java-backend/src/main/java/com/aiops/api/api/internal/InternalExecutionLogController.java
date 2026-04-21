package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.skill.ExecutionLogEntity;
import com.aiops.api.domain.skill.ExecutionLogRepository;
import jakarta.validation.constraints.NotBlank;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;

/** Write surface for run results — sidecar pushes execution log rows here. */
@RestController
@RequestMapping("/internal/execution-logs")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalExecutionLogController {

	private final ExecutionLogRepository repository;

	public InternalExecutionLogController(ExecutionLogRepository repository) {
		this.repository = repository;
	}

	@PostMapping
	@Transactional
	public ApiResponse<Dto> create(@Validated @RequestBody CreateRequest req) {
		ExecutionLogEntity e = new ExecutionLogEntity();
		e.setSkillId(req.skillId() == null ? -1L : req.skillId());
		e.setAutoPatrolId(req.autoPatrolId());
		e.setScriptVersionId(req.scriptVersionId());
		e.setCronJobId(req.cronJobId());
		e.setTriggeredBy(req.triggeredBy());
		e.setEventContext(req.eventContext());
		e.setStatus(req.status() == null ? "success" : req.status());
		e.setLlmReadableData(req.llmReadableData());
		e.setActionDispatched(req.actionDispatched());
		e.setErrorMessage(req.errorMessage());
		if (req.finishedAt() != null) e.setFinishedAt(req.finishedAt());
		e.setDurationMs(req.durationMs());
		return ApiResponse.ok(Dto.of(repository.save(e)));
	}

	@PatchMapping("/{id}/finish")
	@Transactional
	public ApiResponse<Dto> finish(@PathVariable Long id, @RequestBody FinishRequest req) {
		ExecutionLogEntity e = repository.findById(id).orElseThrow();
		e.setStatus(req.status() == null ? "success" : req.status());
		e.setFinishedAt(OffsetDateTime.now());
		if (req.llmReadableData() != null) e.setLlmReadableData(req.llmReadableData());
		if (req.errorMessage() != null) e.setErrorMessage(req.errorMessage());
		if (req.durationMs() != null) e.setDurationMs(req.durationMs());
		return ApiResponse.ok(Dto.of(repository.save(e)));
	}

	public record CreateRequest(Long skillId, Long autoPatrolId, Long scriptVersionId, Long cronJobId,
	                            @NotBlank String triggeredBy, String eventContext, String status,
	                            String llmReadableData, String actionDispatched, String errorMessage,
	                            OffsetDateTime finishedAt, Long durationMs) {}

	public record FinishRequest(String status, String llmReadableData, String errorMessage, Long durationMs) {}

	public record Dto(Long id, Long skillId, Long autoPatrolId, String triggeredBy, String status,
	                  OffsetDateTime startedAt, OffsetDateTime finishedAt, Long durationMs) {
		static Dto of(ExecutionLogEntity e) {
			return new Dto(e.getId(), e.getSkillId(), e.getAutoPatrolId(), e.getTriggeredBy(),
					e.getStatus(), e.getStartedAt(), e.getFinishedAt(), e.getDurationMs());
		}
	}
}
