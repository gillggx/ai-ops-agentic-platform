package com.aiops.api.api.pipeline;

import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.pipeline.BlockEntity;
import com.aiops.api.domain.pipeline.BlockRepository;
import com.aiops.api.domain.pipeline.PipelineAutoCheckTriggerRepository;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.pipeline.PublishedSkillEntity;
import com.aiops.api.domain.pipeline.PublishedSkillRepository;
import com.aiops.api.config.AiopsProperties;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.reactive.function.client.WebClient;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Path-parity wrapper: Frontend proxies call {@code /api/v1/pipeline-builder/*}
 * which is how the old Python namespaced these endpoints. New native Java paths
 * are under {@code /api/v1/pipelines}, {@code /api/v1/published-skills} etc.
 * We keep both namespaces until Phase 8 retires the path aliases.
 */
@RestController
@RequestMapping("/api/v1/pipeline-builder")
@PreAuthorize(Authorities.ANY_ROLE)
public class PipelineBuilderController {

	private final PipelineRepository pipelineRepo;
	private final BlockRepository blockRepo;
	private final PublishedSkillRepository publishedSkillRepo;
	private final PipelineAutoCheckTriggerRepository autoCheckRepo;
	private final ObjectMapper mapper;
	private final AiopsProperties props;
	// Phase 8-A-1d: forward execute/validate to the Python sidecar instead
	// of the decommissioned :8001 backend. The sidecar already runs the
	// 27 BUILTIN_EXECUTORS in-process (block_runtime + pipeline_builder).
	private final WebClient sidecarClient;

	public PipelineBuilderController(PipelineRepository pipelineRepo,
	                                 BlockRepository blockRepo,
	                                 PublishedSkillRepository publishedSkillRepo,
	                                 PipelineAutoCheckTriggerRepository autoCheckRepo,
	                                 ObjectMapper mapper,
	                                 AiopsProperties props,
	                                 WebClient pythonSidecarWebClient) {
		this.pipelineRepo = pipelineRepo;
		this.blockRepo = blockRepo;
		this.publishedSkillRepo = publishedSkillRepo;
		this.autoCheckRepo = autoCheckRepo;
		this.mapper = mapper;
		this.props = props;
		// Wrap the auto-configured sidecar client with a larger response
		// buffer — Pipeline executions can return big DataFrame previews.
		this.sidecarClient = pythonSidecarWebClient.mutate()
				.codecs(c -> c.defaultCodecs().maxInMemorySize(16 * 1024 * 1024))
				.build();
	}

	/** Parse a text column that stores JSON; return original string on parse error. */
	private Object parseJsonOrRaw(String raw) {
		if (raw == null || raw.isBlank()) return null;
		try { return mapper.readTree(raw); }
		catch (JsonProcessingException e) { return raw; }
	}

	/** Convert a BlockEntity to a Frontend-friendly map with JSON text
	 *  columns parsed. Frontend's BlockSpec.input_schema / output_schema /
	 *  param_schema / examples expect arrays/objects, not raw strings. */
	private Map<String, Object> blockDto(BlockEntity b) {
		Map<String, Object> m = new HashMap<>();
		m.put("id", b.getId());
		m.put("name", b.getName());
		m.put("category", b.getCategory());
		m.put("version", b.getVersion());
		m.put("status", b.getStatus());
		m.put("description", b.getDescription());
		m.put("input_schema", parseJsonOrRaw(b.getInputSchema()));
		m.put("output_schema", parseJsonOrRaw(b.getOutputSchema()));
		m.put("param_schema", parseJsonOrRaw(b.getParamSchema()));
		m.put("examples", parseJsonOrRaw(b.getExamples()));
		m.put("output_columns_hint", parseJsonOrRaw(b.getOutputColumnsHint()));
		m.put("implementation", b.getImplementation());
		m.put("is_custom", b.getIsCustom());
		m.put("created_by", b.getCreatedBy());
		m.put("approved_by", b.getApprovedBy());
		m.put("approved_at", b.getApprovedAt());
		m.put("review_note", b.getReviewNote());
		m.put("created_at", b.getCreatedAt());
		m.put("updated_at", b.getUpdatedAt());
		return m;
	}

	@GetMapping("/pipelines")
	public List<PipelineEntity> listPipelines(@RequestParam(required = false) String status) {
		return (status != null && !status.isBlank())
				? pipelineRepo.findByStatus(status) : pipelineRepo.findAll();
	}

	@GetMapping("/pipelines/{id}")
	public PipelineEntity getPipeline(@PathVariable Long id) {
		return pipelineRepo.findById(id).orElseThrow(() -> ApiException.notFound("pipeline"));
	}

	@GetMapping("/blocks")
	public List<Map<String, Object>> listBlocks() {
		return blockRepo.findAll().stream().map(this::blockDto).toList();
	}

	@GetMapping("/published-skills")
	public List<PublishedSkillEntity> listPublishedSkills(@RequestParam(required = false) String status) {
		return (status != null && !status.isBlank())
				? publishedSkillRepo.findByStatus(status) : publishedSkillRepo.findAll();
	}

	@GetMapping("/auto-check-rules")
	public List<Map<String, Object>> listAutoCheckRules() {
		// Returns real rows joined with pipeline name + status so the Frontend
		// Auto-Check Rules page can list bindings.
		List<com.aiops.api.domain.pipeline.PipelineAutoCheckTriggerEntity> triggers = autoCheckRepo.findAll();
		if (triggers.isEmpty()) return List.of();

		// Bulk fetch referenced pipelines for name+status lookup.
		var pipelineIds = triggers.stream().map(
				com.aiops.api.domain.pipeline.PipelineAutoCheckTriggerEntity::getPipelineId).toList();
		var pipelines = pipelineRepo.findAllById(pipelineIds).stream()
				.collect(java.util.stream.Collectors.toMap(PipelineEntity::getId, p -> p));
		return triggers.stream().map(t -> {
			Map<String, Object> m = new HashMap<>();
			m.put("id", t.getId());
			m.put("pipeline_id", t.getPipelineId());
			PipelineEntity p = pipelines.get(t.getPipelineId());
			m.put("pipeline_name", p != null ? p.getName() : null);
			m.put("pipeline_status", p != null ? p.getStatus() : null);
			m.put("event_type", t.getEventType());
			m.put("created_at", t.getCreatedAt());
			return m;
		}).toList();
	}

	// ── POST /execute — forward to sidecar /internal/pipeline/execute ────
	// The Python sidecar runs the full 27-block executor in-process; service
	// token is auto-injected by pythonSidecarWebClient (PythonSidecarConfig).
	@PostMapping("/execute")
	@SuppressWarnings({"unchecked", "rawtypes"})
	public Map<String, Object> execute(@RequestBody Map<String, Object> body) {
		return sidecarClient.post()
				.uri("/internal/pipeline/execute")
				.header("Content-Type", "application/json")
				.bodyValue(body)
				.retrieve()
				.bodyToMono(Map.class)
				.block();
	}

	// ── POST /validate — forward to sidecar /internal/pipeline/validate ──
	@PostMapping("/validate")
	@SuppressWarnings({"unchecked", "rawtypes"})
	public Map<String, Object> validate(@RequestBody Map<String, Object> body) {
		return sidecarClient.post()
				.uri("/internal/pipeline/validate")
				.header("Content-Type", "application/json")
				.bodyValue(body)
				.retrieve()
				.bodyToMono(Map.class)
				.block();
	}

	// ── POST /preview — forward to sidecar /internal/pipeline/preview.
	// Builder's RUN PREVIEW button needs this. The route was missed during
	// the cutover from fastapi-backend; without it the frontend got a
	// 'Internal server error' from a 404-as-NoResourceFoundException.
	@PostMapping("/preview")
	@SuppressWarnings({"unchecked", "rawtypes"})
	public Map<String, Object> preview(@RequestBody Map<String, Object> body) {
		return sidecarClient.post()
				.uri("/internal/pipeline/preview")
				.header("Content-Type", "application/json")
				.bodyValue(body)
				.retrieve()
				.bodyToMono(Map.class)
				.block();
	}
}
