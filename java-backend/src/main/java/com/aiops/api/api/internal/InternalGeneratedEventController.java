package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.event.GeneratedEventEntity;
import com.aiops.api.domain.event.GeneratedEventRepository;
import com.aiops.api.patrol.EventDispatchService;
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
	private final EventDispatchService dispatchService;

	public InternalGeneratedEventController(GeneratedEventRepository repository,
	                                        EventDispatchService dispatchService) {
		this.repository = repository;
		this.dispatchService = dispatchService;
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
		// Phase C — fan out to event-mode auto_patrols. Async + swallow errors
		// so the writer's response isn't held up by downstream patrol fires.
		dispatchService.dispatchGeneratedEvent(saved.getEventTypeId(), saved.getMappedParameters());
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
