package com.aiops.api.api.patrol;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.patrol.AutoPatrolEntity;
import com.aiops.api.domain.patrol.AutoPatrolRepository;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
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
	private final PipelineRepository pipelineRepo;
	private final com.aiops.api.domain.skill.ExecutionLogRepository execLogRepo;
	private final com.aiops.api.patrol.AutoPatrolSchedulerService schedulerService;
	private final com.aiops.api.patrol.AutoPatrolExecutor executor;

	public AutoPatrolController(AutoPatrolRepository repository,
	                            PipelineRepository pipelineRepo,
	                            com.aiops.api.domain.skill.ExecutionLogRepository execLogRepo,
	                            com.aiops.api.patrol.AutoPatrolSchedulerService schedulerService,
	                            com.aiops.api.patrol.AutoPatrolExecutor executor) {
		this.repository = repository;
		this.pipelineRepo = pipelineRepo;
		this.execLogRepo = execLogRepo;
		this.schedulerService = schedulerService;
		this.executor = executor;
	}

	@GetMapping
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<Dtos.Summary>> list(@RequestParam(required = false) Boolean active) {
		List<AutoPatrolEntity> all = Boolean.TRUE.equals(active)
				? repository.findByIsActiveTrue() : repository.findAll();
		// Build pipeline_id → pipeline.name map so the wizard / picker can show
		// users the bound pipeline's name (the patrol's own name is often a
		// generic auto-generated string like "[Patrol] 新 Pipeline").
		java.util.Set<Long> pids = all.stream()
				.map(AutoPatrolEntity::getPipelineId)
				.filter(java.util.Objects::nonNull)
				.collect(java.util.stream.Collectors.toSet());
		java.util.Map<Long, String> nameById = pids.isEmpty() ? java.util.Map.of()
				: java.util.stream.StreamSupport.stream(
						pipelineRepo.findAllById(pids).spliterator(), false)
				.collect(java.util.stream.Collectors.toMap(
						PipelineEntity::getId, PipelineEntity::getName, (a, b) -> a));
		return ApiResponse.ok(all.stream()
				.map(e -> Dtos.summaryOf(e, nameById.get(e.getPipelineId())))
				.toList());
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
		AutoPatrolEntity saved = repository.save(e);
		schedulerService.refresh(saved.getId());
		return ApiResponse.ok(Dtos.detailOf(saved));
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
		AutoPatrolEntity saved = repository.save(e);
		schedulerService.refresh(saved.getId());
		return ApiResponse.ok(Dtos.detailOf(saved));
	}

	@DeleteMapping("/{id}")
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<Void> delete(@PathVariable Long id) {
		if (!repository.existsById(id)) throw ApiException.notFound("auto patrol");
		repository.deleteById(id);
		schedulerService.unregister(id);
		return ApiResponse.ok(null);
	}

	/**
	 * Manually trigger a patrol — synchronously runs the executor (scope
	 * expansion → per-target sidecar execute → alarm write) and returns a
	 * summary. Skips the {@code is_active} check on purpose so admins can
	 * test paused patrols without flipping the flag.
	 */
	@PostMapping("/{id}/trigger")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<java.util.Map<String, Object>> trigger(@PathVariable Long id) {
		if (!repository.existsById(id)) throw ApiException.notFound("auto patrol");
		var result = executor.executePatrol(id);
		java.util.Map<String, Object> body = new java.util.LinkedHashMap<>();
		body.put("run_id", result.runId());
		body.put("patrol_id", result.patrolId());
		body.put("pipeline_id", result.pipelineId());
		body.put("fanout_count", result.fanoutCount());
		body.put("triggered_count", result.triggeredCount());
		body.put("status", result.status());
		body.put("error_message", result.errorMessage());
		return ApiResponse.ok(body);
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
		                      Boolean isActive, Long pipelineId, String pipelineName, Long skillId,
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

		static Summary summaryOf(AutoPatrolEntity e, String pipelineName) {
			return new Summary(e.getId(), e.getName(), e.getTriggerMode(), e.getCronExpr(),
					e.getIsActive(), e.getPipelineId(), pipelineName, e.getSkillId(), e.getUpdatedAt());
		}

		// Back-compat overload: callers that don't have the join data yet pass
		// null for pipelineName so the response still serialises.
		static Summary summaryOf(AutoPatrolEntity e) {
			return summaryOf(e, null);
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
