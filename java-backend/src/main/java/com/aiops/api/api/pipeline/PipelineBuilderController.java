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
	private final WebClient legacyClient;

	public PipelineBuilderController(PipelineRepository pipelineRepo,
	                                 BlockRepository blockRepo,
	                                 PublishedSkillRepository publishedSkillRepo,
	                                 PipelineAutoCheckTriggerRepository autoCheckRepo,
	                                 ObjectMapper mapper,
	                                 AiopsProperties props,
	                                 @Value("${aiops.legacy-backend-url:http://127.0.0.1:8001}") String legacyBackendUrl) {
		this.pipelineRepo = pipelineRepo;
		this.blockRepo = blockRepo;
		this.publishedSkillRepo = publishedSkillRepo;
		this.autoCheckRepo = autoCheckRepo;
		this.mapper = mapper;
		this.props = props;
		this.legacyClient = WebClient.builder()
				.baseUrl(legacyBackendUrl)
				.codecs(c -> c.defaultCodecs().maxInMemorySize(16 * 1024 * 1024))  // pipelines may return big DataFrame previews
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
	public List<Object> listAutoCheckRules() {
		// Bare list (matches sibling endpoints + Python shape). The page
		// calls res.json() straight into `setRows(...)` so a wrapped envelope
		// would crash rendering.
		return List.of();
	}

	// ── POST /execute — proxy to legacy Python :8001 ─────────────────────
	// Full pipeline execution (PipelineExecutor + block registry + MCP calls
	// to simulator) still lives in Python. Java proxies the call until the
	// executor is ported. Frontend "Run" button hits this.
	@PostMapping("/execute")
	@SuppressWarnings({"unchecked", "rawtypes"})
	public Map<String, Object> execute(@RequestBody Map<String, Object> body) {
		String secret = props.auth() != null ? props.auth().sharedSecretToken() : null;
		if (secret == null || secret.isBlank()) {
			throw new com.aiops.api.common.ApiException(
					org.springframework.http.HttpStatus.INTERNAL_SERVER_ERROR,
					"internal_error",
					"AIOPS_SHARED_SECRET_TOKEN not configured — cannot reach legacy executor");
		}
		return legacyClient.post()
				.uri("/api/v1/pipeline-builder/execute")
				.header("Authorization", "Bearer " + secret)
				.header("Content-Type", "application/json")
				.bodyValue(body)
				.retrieve()
				.bodyToMono(Map.class)
				.block();
	}

	// ── POST /validate — same pattern (used by agent Glass Box flow) ─────
	@PostMapping("/validate")
	@SuppressWarnings({"unchecked", "rawtypes"})
	public Map<String, Object> validate(@RequestBody Map<String, Object> body) {
		String secret = props.auth() != null ? props.auth().sharedSecretToken() : null;
		if (secret == null || secret.isBlank()) {
			throw new com.aiops.api.common.ApiException(
					org.springframework.http.HttpStatus.INTERNAL_SERVER_ERROR,
					"internal_error",
					"AIOPS_SHARED_SECRET_TOKEN not configured");
		}
		return legacyClient.post()
				.uri("/api/v1/pipeline-builder/validate")
				.header("Authorization", "Bearer " + secret)
				.header("Content-Type", "application/json")
				.bodyValue(body)
				.retrieve()
				.bodyToMono(Map.class)
				.block();
	}
}
