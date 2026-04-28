package com.aiops.api.api.event;

import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.event.EventTypeEntity;
import com.aiops.api.domain.event.EventTypeRepository;
import jakarta.validation.constraints.NotBlank;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1/event-types")
public class EventTypeController {

	private final EventTypeRepository repository;

	public EventTypeController(EventTypeRepository repository) {
		this.repository = repository;
	}

	@GetMapping
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<EventTypeDtos.Detail>> list() {
		return ApiResponse.ok(repository.findAll().stream().map(EventTypeDtos::of).toList());
	}

	@GetMapping("/{id}")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<EventTypeDtos.Detail> get(@PathVariable Long id) {
		EventTypeEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("event type"));
		return ApiResponse.ok(EventTypeDtos.of(e));
	}

	@PostMapping
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<EventTypeDtos.Detail> create(@Validated @RequestBody EventTypeDtos.CreateRequest req) {
		if (repository.findByName(req.name()).isPresent()) {
			throw ApiException.conflict("event type name already exists");
		}
		EventTypeEntity e = new EventTypeEntity();
		e.setName(req.name());
		e.setDescription(req.description() == null ? "" : req.description());
		e.setSource(req.source() == null ? "simulator" : req.source());
		e.setIsActive(req.isActive() == null ? Boolean.TRUE : req.isActive());
		// SPEC_patrol_pipeline_wiring §1.1 — attributes ships as a JSON-encoded
		// string ([{name,type,required,...}, ...]) so the frontend's attribute
		// editor can round-trip without us re-serialising it.
		if (req.attributes() != null && !req.attributes().isBlank()) {
			e.setAttributes(req.attributes());
		}
		return ApiResponse.ok(EventTypeDtos.of(repository.save(e)));
	}

	@PutMapping("/{id}")
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<EventTypeDtos.Detail> update(@PathVariable Long id,
	                                                @Validated @RequestBody EventTypeDtos.UpdateRequest req) {
		EventTypeEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("event type"));
		if (req.description() != null) e.setDescription(req.description());
		if (req.source() != null) e.setSource(req.source());
		if (req.isActive() != null) e.setIsActive(req.isActive());
		if (req.attributes() != null) e.setAttributes(req.attributes());
		return ApiResponse.ok(EventTypeDtos.of(repository.save(e)));
	}

	@DeleteMapping("/{id}")
	@Transactional
	@PreAuthorize(Authorities.ADMIN)
	public ApiResponse<Void> delete(@PathVariable Long id) {
		if (!repository.existsById(id)) throw ApiException.notFound("event type");
		repository.deleteById(id);
		return ApiResponse.ok(null);
	}

	/** Event log — Phase 2 path-parity stub (Python computes from nats_event_logs). */
	@GetMapping("/{id}/log")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<java.util.Map<String, Object>> log(@PathVariable Long id,
	                                                      @RequestParam(defaultValue = "10") int limit) {
		EventTypeEntity et = repository.findById(id).orElseThrow(() -> ApiException.notFound("event type"));
		java.util.Map<String, Object> out = new java.util.HashMap<>();
		out.put("event_type_name", et.getName());
		out.put("event_type_id", et.getId());
		out.put("nats_total", 0L);
		out.put("poller_total", 0L);
		out.put("recent", java.util.List.of());
		return ApiResponse.ok(out);
	}

	public static final class EventTypeDtos {

		public record Detail(Long id, String name, String description, String source,
		                     Boolean isActive, String attributes, String diagnosisSkillIds) {}

		public record CreateRequest(@NotBlank String name, String description, String source,
		                            Boolean isActive, String attributes) {}

		public record UpdateRequest(String description, String source, Boolean isActive, String attributes) {}

		static Detail of(EventTypeEntity e) {
			return new Detail(e.getId(), e.getName(), e.getDescription(), e.getSource(),
					e.getIsActive(), e.getAttributes(), e.getDiagnosisSkillIds());
		}
	}
}
