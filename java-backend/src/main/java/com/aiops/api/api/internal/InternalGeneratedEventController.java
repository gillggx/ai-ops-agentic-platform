package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.event.GeneratedEventEntity;
import com.aiops.api.domain.event.GeneratedEventRepository;
import com.aiops.api.scheduler.SchedulerHttpClient;
import jakarta.validation.constraints.NotNull;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

/** Skills emit generated events (e.g. routine check → alarm) via this endpoint. */
@RestController
@RequestMapping("/internal/generated-events")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalGeneratedEventController {

	private final GeneratedEventRepository repository;
	private final SchedulerHttpClient scheduler;

	public InternalGeneratedEventController(GeneratedEventRepository repository,
	                                        SchedulerHttpClient scheduler) {
		this.repository = repository;
		this.scheduler = scheduler;
	}

	@PostMapping
	@Transactional
	public ApiResponse<Dto> create(@Validated @RequestBody CreateRequest req) {
		GeneratedEventEntity e = new GeneratedEventEntity();
		e.setEventTypeId(req.eventTypeId());
		e.setSourceSkillId(req.sourceSkillId());
		e.setSourceRoutineCheckId(req.sourceRoutineCheckId());
		if (req.mappedParameters() != null) e.setMappedParameters(req.mappedParameters());
		e.setSkillConclusion(req.skillConclusion());
		if (req.status() != null) e.setStatus(req.status());
		GeneratedEventEntity saved = repository.save(e);
		// Phase 2 — fan out to event-mode auto_patrols via the scheduler
		// service. Best-effort: a scheduler outage doesn't fail the event
		// write; scheduler's reconcileAll loop catches drift on next tick.
		scheduler.dispatchEvent(saved.getEventTypeId(), saved.getMappedParameters());
		return ApiResponse.ok(Dto.of(saved));
	}

	public record CreateRequest(@NotNull Long eventTypeId, @NotNull Long sourceSkillId,
	                            Long sourceRoutineCheckId, String mappedParameters,
	                            String skillConclusion, String status) {}

	public record Dto(Long id, Long eventTypeId, Long sourceSkillId, String status,
	                  java.time.OffsetDateTime createdAt) {
		static Dto of(GeneratedEventEntity e) {
			return new Dto(e.getId(), e.getEventTypeId(), e.getSourceSkillId(),
					e.getStatus(), e.getCreatedAt());
		}
	}
}
