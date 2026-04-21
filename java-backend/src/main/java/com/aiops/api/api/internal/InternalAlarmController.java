package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import jakarta.validation.constraints.NotNull;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;

/** Patrol / pipeline runs publishing alarms back from the sidecar. */
@RestController
@RequestMapping("/internal/alarms")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalAlarmController {

	private final AlarmRepository repository;

	public InternalAlarmController(AlarmRepository repository) {
		this.repository = repository;
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
		return ApiResponse.ok(Dto.of(repository.save(e)));
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
