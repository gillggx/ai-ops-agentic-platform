package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * Read surface for the Python sidecar. Returns the full pipeline payload
 * (including DAG JSON) the executor / LangGraph need to do their work.
 *
 * <p>Guarded by {@link InternalAuthority#PYTHON_SIDECAR}; reachable only via
 * {@code /internal/*} paths protected by {@code InternalServiceTokenFilter}.
 */
@RestController
@RequestMapping("/internal/pipelines")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalPipelineController {

	private final PipelineRepository repository;

	public InternalPipelineController(PipelineRepository repository) {
		this.repository = repository;
	}

	@GetMapping("/{id}")
	public ApiResponse<InternalPipelineDto> get(@PathVariable Long id) {
		PipelineEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("pipeline"));
		return ApiResponse.ok(InternalPipelineDto.of(e));
	}

	@GetMapping
	public ApiResponse<List<InternalPipelineDto>> list(@RequestParam(required = false) String status) {
		var all = (status != null && !status.isBlank())
				? repository.findByStatus(status) : repository.findAll();
		return ApiResponse.ok(all.stream().map(InternalPipelineDto::of).toList());
	}

	public record InternalPipelineDto(Long id, String name, String status, String pipelineKind,
	                                  String version, String pipelineJson, Long createdBy) {
		static InternalPipelineDto of(PipelineEntity e) {
			return new InternalPipelineDto(e.getId(), e.getName(), e.getStatus(), e.getPipelineKind(),
					e.getVersion(), e.getPipelineJson(), e.getCreatedBy());
		}
	}
}
