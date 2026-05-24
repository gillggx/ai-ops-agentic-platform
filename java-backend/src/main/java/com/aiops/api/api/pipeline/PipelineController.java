package com.aiops.api.api.pipeline;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * Pipeline CRUD + lifecycle HTTP layer.
 *
 * <p>After Phase 12 Java OOP refactor (2026-05-23) this controller binds
 * parameters, dispatches to {@link PipelineService}, and wraps the response
 * in {@link ApiResponse} or {@link PipelineDtos}. All business logic
 * (structural validation, state machine, cross-entity writes, JSON serdes)
 * lives in the service.
 */
@RestController
@RequestMapping("/api/v1/pipelines")
public class PipelineController {

	private final PipelineService service;

	public PipelineController(PipelineService service) {
		this.service = service;
	}

	// ── CRUD ────────────────────────────────────────────────────────────────

	@GetMapping
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<PipelineDtos.Summary>> list(@RequestParam(required = false) String status) {
		return ApiResponse.ok(service.list(status).stream().map(PipelineDtos::summaryOf).toList());
	}

	@GetMapping("/{id}")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<PipelineDtos.Detail> get(@PathVariable Long id) {
		return ApiResponse.ok(PipelineDtos.detailOf(service.get(id)));
	}

	@PostMapping
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<PipelineDtos.Detail> create(@Validated @RequestBody PipelineDtos.CreateRequest req,
	                                               @AuthenticationPrincipal AuthPrincipal caller) {
		return ApiResponse.ok(PipelineDtos.detailOf(service.create(req, caller)));
	}

	@PutMapping("/{id}")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<PipelineDtos.Detail> update(@PathVariable Long id,
	                                               @Validated @RequestBody PipelineDtos.UpdateRequest req) {
		return ApiResponse.ok(PipelineDtos.detailOf(service.update(id, req)));
	}

	@DeleteMapping("/{id}")
	@PreAuthorize(Authorities.ADMIN)
	public ApiResponse<Void> delete(@PathVariable Long id) {
		service.delete(id);
		return ApiResponse.ok(null);
	}

	@PostMapping("/{id}/fork")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<PipelineDtos.Detail> fork(@PathVariable Long id,
	                                              @AuthenticationPrincipal AuthPrincipal caller) {
		return ApiResponse.ok(PipelineDtos.detailOf(service.fork(id, caller)));
	}

	@GetMapping("/{id}/runs")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<PipelineDtos.RunSummary>> listRuns(@PathVariable Long id,
	                                                            @RequestParam(defaultValue = "20") int limit) {
		return ApiResponse.ok(service.listRuns(id, limit).stream().map(PipelineDtos::runSummaryOf).toList());
	}

	// ── Lifecycle ───────────────────────────────────────────────────────────

	@PostMapping("/{id}/transition")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<PipelineDtos.Detail> transition(@PathVariable Long id,
	                                                    @Validated @RequestBody PipelineDtos.TransitionRequest req) {
		return ApiResponse.ok(PipelineDtos.detailOf(service.transition(id, req.to())));
	}

	@PostMapping("/{id}/archive")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<PipelineDtos.Detail> archive(@PathVariable Long id) {
		return ApiResponse.ok(PipelineDtos.detailOf(service.archive(id)));
	}

	@PostMapping("/{id}/publish/draft-doc")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<Map<String, Object>> publishDraftDoc(@PathVariable Long id) {
		return ApiResponse.ok(service.publishDraftDoc(id));
	}

	@PostMapping("/{id}/publish")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<Map<String, Object>> publish(@PathVariable Long id,
	                                                 @Validated @RequestBody PipelineDtos.PublishRequest req) {
		return ApiResponse.ok(service.publish(id, req));
	}

	// ── AutoCheck triggers ──────────────────────────────────────────────────

	@PostMapping("/{id}/publish-auto-check")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<Map<String, Object>> publishAutoCheck(@PathVariable Long id,
	                                                          @Validated @RequestBody PipelineDtos.PublishAutoCheckRequest req) {
		return ApiResponse.ok(service.publishAutoCheck(id, req));
	}

	@PutMapping("/{id}/auto-check-triggers")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<Map<String, Object>> upsertAutoCheckTriggers(@PathVariable Long id,
	                                                                @Validated @RequestBody PipelineDtos.PublishAutoCheckRequest req) {
		return ApiResponse.ok(service.upsertAutoCheckTriggers(id, req));
	}

	@GetMapping("/{id}/auto-check-triggers")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<PipelineDtos.AutoCheckTriggerView>> listAutoCheckTriggers(@PathVariable Long id) {
		return ApiResponse.ok(service.listAutoCheckTriggers(id));
	}
}
