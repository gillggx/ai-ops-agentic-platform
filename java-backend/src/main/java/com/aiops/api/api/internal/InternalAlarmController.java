package com.aiops.api.api.internal;

import com.aiops.api.api.alarm.AlarmClusterService;
import com.aiops.api.api.alarm.AlarmDtos;
import com.aiops.api.api.alarm.AlarmEnrichmentService;
import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.scheduler.SchedulerHttpClient;
import jakarta.validation.constraints.NotNull;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.util.Map;

/** Patrol / pipeline runs publishing alarms back from the sidecar (POST), plus
 *  read endpoints the internal Coordinator agent uses when IT admin grants it
 *  the alarm capabilities 對內 (Phase 6). */
@RestController
@RequestMapping("/internal/alarms")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalAlarmController {

	private final AlarmRepository repository;
	private final SchedulerHttpClient scheduler;
	private final AlarmClusterService clusterService;
	private final AlarmEnrichmentService enrichment;

	public InternalAlarmController(AlarmRepository repository,
	                                SchedulerHttpClient scheduler,
	                                AlarmClusterService clusterService,
	                                AlarmEnrichmentService enrichment) {
		this.repository = repository;
		this.scheduler = scheduler;
		this.clusterService = clusterService;
		this.enrichment = enrichment;
	}

	/** Fab-wide 告警現況 — clusters + KPIs (Coordinator's list_alarms). */
	@GetMapping("/situation")
	public ApiResponse<Map<String, Object>> situation(
			@RequestParam(name = "since_hours", defaultValue = "24") int sinceHours) {
		return ApiResponse.ok(Map.of(
				"clusters", clusterService.computeClusters(sinceHours, null),
				"kpis", clusterService.computeKpis(sinceHours)));
	}

	/** One alarm's full diagnosis (Coordinator's get_alarm_detail). */
	@GetMapping("/{id}")
	public ApiResponse<AlarmDtos.Detail> detail(@PathVariable Long id) {
		AlarmEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("alarm"));
		return ApiResponse.ok(enrichment.enrichDetail(e));
	}

	@PostMapping
	@Transactional
	public ApiResponse<Dto> create(@Validated @RequestBody CreateRequest req) {
		AlarmEntity e = new AlarmEntity();
		e.setSkillId(req.skillId());
		if (req.triggerEvent() != null) e.setTriggerEvent(req.triggerEvent());
		if (req.equipmentId() != null) e.setEquipmentId(req.equipmentId());
		if (req.lotId() != null) e.setLotId(req.lotId());
		e.setStep(req.step());
		e.setEventTime(req.eventTime());
		if (req.severity() != null) e.setSeverity(req.severity());
		if (req.title() != null) e.setTitle(req.title());
		e.setSummary(req.summary());
		e.setExecutionLogId(req.executionLogId());
		e.setDiagnosticLogId(req.diagnosticLogId());
		AlarmEntity saved = repository.save(e);
		// Phase 2 — fan out via scheduler (fail-open).
		scheduler.dispatchAlarm(saved.getId());
		return ApiResponse.ok(Dto.of(saved));
	}

	public record CreateRequest(@NotNull Long skillId, String triggerEvent, String equipmentId,
	                            String lotId, String step, OffsetDateTime eventTime,
	                            String severity, String title, String summary,
	                            Long executionLogId, Long diagnosticLogId) {}

	public record Dto(Long id, Long skillId, String severity, String title, String status,
	                  OffsetDateTime createdAt) {
		static Dto of(AlarmEntity e) {
			return new Dto(e.getId(), e.getSkillId(), e.getSeverity(), e.getTitle(),
					e.getStatus(), e.getCreatedAt());
		}
	}
}
