package com.aiops.api.api.pipeline;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import jakarta.validation.constraints.NotBlank;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.Set;

@RestController
@RequestMapping("/api/v1/pipelines")
public class PipelineController {

	private final PipelineRepository repository;

	public PipelineController(PipelineRepository repository) {
		this.repository = repository;
	}

	@GetMapping
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<PipelineDtos.Summary>> list(@RequestParam(required = false) String status) {
		List<PipelineEntity> all = (status != null && !status.isBlank())
				? repository.findByStatus(status) : repository.findAll();
		return ApiResponse.ok(all.stream().map(PipelineDtos::summaryOf).toList());
	}

	@GetMapping("/{id}")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<PipelineDtos.Detail> get(@PathVariable Long id) {
		PipelineEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("pipeline"));
		return ApiResponse.ok(PipelineDtos.detailOf(e));
	}

	@PostMapping
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<PipelineDtos.Detail> create(@Validated @RequestBody PipelineDtos.CreateRequest req,
	                                               @AuthenticationPrincipal AuthPrincipal caller) {
		PipelineEntity e = new PipelineEntity();
		e.setName(req.name());
		if (req.description() != null) e.setDescription(req.description());
		if (req.pipelineKind() != null) e.setPipelineKind(req.pipelineKind());
		if (req.pipelineJson() != null) e.setPipelineJson(req.pipelineJson());
		if (req.version() != null) e.setVersion(req.version());
		e.setCreatedBy(caller.userId());
		return ApiResponse.ok(PipelineDtos.detailOf(repository.save(e)));
	}

	@PutMapping("/{id}")
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<PipelineDtos.Detail> update(@PathVariable Long id,
	                                               @Validated @RequestBody PipelineDtos.UpdateRequest req) {
		PipelineEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("pipeline"));
		if ("locked".equalsIgnoreCase(e.getStatus()) || "archived".equalsIgnoreCase(e.getStatus())) {
			throw ApiException.conflict("pipeline is " + e.getStatus() + "; cannot mutate");
		}
		if (req.name() != null) e.setName(req.name());
		if (req.description() != null) e.setDescription(req.description());
		if (req.pipelineKind() != null) e.setPipelineKind(req.pipelineKind());
		if (req.pipelineJson() != null) e.setPipelineJson(req.pipelineJson());
		if (req.autoDoc() != null) e.setAutoDoc(req.autoDoc());
		return ApiResponse.ok(PipelineDtos.detailOf(repository.save(e)));
	}

	// 5-stage lifecycle: draft → validating → locked → active → archived.
	// Phase 1 ports the state machine + timestamps; structural validation
	// (PipelineValidator + kind-specific checks) is deferred to Phase 2.
	private static final Map<String, Set<String>> ALLOWED_TRANSITIONS = Map.of(
			"draft",      Set.of("validating", "archived"),
			"validating", Set.of("locked", "draft"),
			"locked",     Set.of("active", "draft"),
			"active",     Set.of("archived"),
			"archived",   Set.of()
	);

	@PostMapping("/{id}/transition")
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<PipelineDtos.Detail> transition(@PathVariable Long id,
	                                                    @Validated @RequestBody PipelineDtos.TransitionRequest req) {
		PipelineEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("pipeline"));
		String from = e.getStatus();
		String to = req.to();
		Set<String> allowed = ALLOWED_TRANSITIONS.getOrDefault(from, Set.of());
		if (!allowed.contains(to)) {
			throw ApiException.conflict("Cannot transition from '" + from + "' to '" + to
					+ "'. Allowed: " + allowed);
		}
		e.setStatus(to);
		OffsetDateTime now = OffsetDateTime.now();
		switch (to) {
			case "locked"   -> e.setLockedAt(now);
			case "active"   -> e.setPublishedAt(now);
			case "archived" -> e.setArchivedAt(now);
			case "draft"    -> { e.setLockedAt(null); e.setLockedBy(null); }
			default -> {}
		}
		return ApiResponse.ok(PipelineDtos.detailOf(repository.save(e)));
	}

	@PostMapping("/{id}/archive")
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<PipelineDtos.Detail> archive(@PathVariable Long id) {
		PipelineEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("pipeline"));
		e.setStatus("archived");
		e.setArchivedAt(OffsetDateTime.now());
		return ApiResponse.ok(PipelineDtos.detailOf(repository.save(e)));
	}

	@DeleteMapping("/{id}")
	@Transactional
	@PreAuthorize(Authorities.ADMIN)
	public ApiResponse<Void> delete(@PathVariable Long id) {
		if (!repository.existsById(id)) throw ApiException.notFound("pipeline");
		repository.deleteById(id);
		return ApiResponse.ok(null);
	}

	public static final class PipelineDtos {

		public record Summary(Long id, String name, String description, String status,
		                      String pipelineKind, String version, Long createdBy,
		                      java.time.OffsetDateTime updatedAt) {}

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

		static Summary summaryOf(PipelineEntity e) {
			return new Summary(e.getId(), e.getName(), e.getDescription(), e.getStatus(),
					e.getPipelineKind(), e.getVersion(), e.getCreatedBy(), e.getUpdatedAt());
		}

		static Detail detailOf(PipelineEntity e) {
			return new Detail(e.getId(), e.getName(), e.getDescription(), e.getStatus(),
					e.getPipelineKind(), e.getVersion(), e.getPipelineJson(), e.getUsageStats(),
					e.getAutoDoc(), e.getCreatedBy(), e.getApprovedBy(), e.getParentId(),
					e.getCreatedAt(), e.getUpdatedAt(), e.getLockedAt(), e.getPublishedAt(),
					e.getArchivedAt());
		}
	}
}
