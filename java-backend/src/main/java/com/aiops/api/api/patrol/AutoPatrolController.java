package com.aiops.api.api.patrol;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.patrol.AutoPatrolEntity;
import com.aiops.api.domain.patrol.AutoPatrolRepository;
import jakarta.validation.constraints.NotBlank;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1/auto-patrols")
public class AutoPatrolController {

	private final AutoPatrolRepository repository;
	private final com.aiops.api.domain.skill.ExecutionLogRepository execLogRepo;

	public AutoPatrolController(AutoPatrolRepository repository,
	                            com.aiops.api.domain.skill.ExecutionLogRepository execLogRepo) {
		this.repository = repository;
		this.execLogRepo = execLogRepo;
	}

	@GetMapping
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<Dtos.Summary>> list(@RequestParam(required = false) Boolean active) {
		List<AutoPatrolEntity> all = Boolean.TRUE.equals(active)
				? repository.findByIsActiveTrue() : repository.findAll();
		return ApiResponse.ok(all.stream().map(Dtos::summaryOf).toList());
	}

	@GetMapping("/{id}")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Dtos.Detail> get(@PathVariable Long id) {
		AutoPatrolEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("auto patrol"));
		return ApiResponse.ok(Dtos.detailOf(e));
	}

	@PostMapping
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<Dtos.Detail> create(@Validated @RequestBody Dtos.CreateRequest req,
	                                       @AuthenticationPrincipal AuthPrincipal caller) {
		AutoPatrolEntity e = new AutoPatrolEntity();
		e.setName(req.name());
		if (req.description() != null) e.setDescription(req.description());
		if (req.triggerMode() != null) e.setTriggerMode(req.triggerMode());
		if (req.cronExpr() != null) e.setCronExpr(req.cronExpr());
		if (req.scheduledAt() != null) e.setScheduledAt(req.scheduledAt());
		if (req.eventTypeId() != null) e.setEventTypeId(req.eventTypeId());
		if (req.pipelineId() != null) e.setPipelineId(req.pipelineId());
		if (req.skillId() != null) e.setSkillId(req.skillId());
		if (req.dataContext() != null) e.setDataContext(req.dataContext());
		if (req.targetScope() != null) e.setTargetScope(req.targetScope());
		if (req.autoCheckDescription() != null) e.setAutoCheckDescription(req.autoCheckDescription());
		if (req.alarmSeverity() != null) e.setAlarmSeverity(req.alarmSeverity());
		if (req.alarmTitle() != null) e.setAlarmTitle(req.alarmTitle());
		if (req.notifyConfig() != null) e.setNotifyConfig(req.notifyConfig());
		if (req.inputBinding() != null) e.setInputBinding(req.inputBinding());
		e.setCreatedBy(caller.userId());
		return ApiResponse.ok(Dtos.detailOf(repository.save(e)));
	}

	@PutMapping("/{id}")
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<Dtos.Detail> update(@PathVariable Long id,
	                                       @Validated @RequestBody Dtos.UpdateRequest req) {
		AutoPatrolEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("auto patrol"));
		if (req.description() != null) e.setDescription(req.description());
		if (req.triggerMode() != null) e.setTriggerMode(req.triggerMode());
		if (req.cronExpr() != null) e.setCronExpr(req.cronExpr());
		if (req.scheduledAt() != null) e.setScheduledAt(req.scheduledAt());
		if (req.eventTypeId() != null) e.setEventTypeId(req.eventTypeId());
		if (req.pipelineId() != null) e.setPipelineId(req.pipelineId());
		if (req.dataContext() != null) e.setDataContext(req.dataContext());
		if (req.targetScope() != null) e.setTargetScope(req.targetScope());
		if (req.autoCheckDescription() != null) e.setAutoCheckDescription(req.autoCheckDescription());
		if (req.alarmSeverity() != null) e.setAlarmSeverity(req.alarmSeverity());
		if (req.alarmTitle() != null) e.setAlarmTitle(req.alarmTitle());
		if (req.notifyConfig() != null) e.setNotifyConfig(req.notifyConfig());
		if (req.inputBinding() != null) e.setInputBinding(req.inputBinding());
		if (req.isActive() != null) e.setIsActive(req.isActive());
		return ApiResponse.ok(Dtos.detailOf(repository.save(e)));
	}

	@DeleteMapping("/{id}")
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<Void> delete(@PathVariable Long id) {
		if (!repository.existsById(id)) throw ApiException.notFound("auto patrol");
		repository.deleteById(id);
		return ApiResponse.ok(null);
	}

	@GetMapping("/{id}/executions")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<java.util.List<com.aiops.api.domain.skill.ExecutionLogEntity>> executions(
			@PathVariable Long id, @RequestParam(defaultValue = "20") int limit) {
		int safe = Math.min(Math.max(limit, 1), 200);
		var pageable = org.springframework.data.domain.PageRequest.of(0, safe);
		return ApiResponse.ok(execLogRepo.findByAutoPatrolIdOrderByStartedAtDesc(id, pageable));
	}

	public static final class Dtos {

		public record Summary(Long id, String name, String triggerMode, String cronExpr,
		                      Boolean isActive, Long pipelineId, Long skillId,
		                      java.time.OffsetDateTime updatedAt) {}

		public record Detail(Long id, String name, String description, Long skillId, Long pipelineId,
		                     String inputBinding, String triggerMode, Long eventTypeId, String cronExpr,
		                     java.time.OffsetDateTime scheduledAt,
		                     String autoCheckDescription, String dataContext, String targetScope,
		                     String alarmSeverity, String alarmTitle, String notifyConfig,
		                     Boolean isActive, Long createdBy, java.time.OffsetDateTime createdAt,
		                     java.time.OffsetDateTime updatedAt) {}

		public record CreateRequest(@NotBlank String name, String description, String triggerMode,
		                            String cronExpr, java.time.OffsetDateTime scheduledAt,
		                            Long eventTypeId, Long pipelineId, Long skillId,
		                            String dataContext, String targetScope, String autoCheckDescription,
		                            String alarmSeverity, String alarmTitle, String notifyConfig,
		                            String inputBinding) {}

		public record UpdateRequest(String description, String triggerMode, String cronExpr,
		                            java.time.OffsetDateTime scheduledAt,
		                            Long eventTypeId, Long pipelineId, String dataContext,
		                            String targetScope, String autoCheckDescription, String alarmSeverity,
		                            String alarmTitle, String notifyConfig, String inputBinding,
		                            Boolean isActive) {}

		static Summary summaryOf(AutoPatrolEntity e) {
			return new Summary(e.getId(), e.getName(), e.getTriggerMode(), e.getCronExpr(),
					e.getIsActive(), e.getPipelineId(), e.getSkillId(), e.getUpdatedAt());
		}

		static Detail detailOf(AutoPatrolEntity e) {
			return new Detail(e.getId(), e.getName(), e.getDescription(), e.getSkillId(), e.getPipelineId(),
					e.getInputBinding(), e.getTriggerMode(), e.getEventTypeId(), e.getCronExpr(),
					e.getScheduledAt(),
					e.getAutoCheckDescription(), e.getDataContext(), e.getTargetScope(),
					e.getAlarmSeverity(), e.getAlarmTitle(), e.getNotifyConfig(),
					e.getIsActive(), e.getCreatedBy(), e.getCreatedAt(), e.getUpdatedAt());
		}
	}
}
