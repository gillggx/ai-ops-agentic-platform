package com.aiops.api.api.pipeline;

import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.pipeline.PublishedSkillEntity;
import com.aiops.api.domain.pipeline.PublishedSkillRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.reactive.function.client.WebClient;

import java.util.List;
import java.util.Map;

/**
 * Path-parity wrapper: Frontend proxies call {@code /api/v1/pipeline-builder/*}
 * which is how the old Python namespaced these endpoints. New native Java paths
 * are under {@code /api/v1/pipelines}, {@code /api/v1/published-skills} etc.
 * We keep both namespaces until Phase 8 retires the path aliases.
 *
 * <p>2026-05-23 (Phase 12 OOP refactor): the JSON-parsing block listing,
 * skill substring-search ranking, and auto-check binding join moved to
 * {@link PipelineBuilderService}. Sidecar forwards stay here because they
 * are pure HTTP transport.
 */
@RestController
@RequestMapping("/api/v1/pipeline-builder")
@PreAuthorize(Authorities.ANY_ROLE)
public class PipelineBuilderController {

	private final PipelineRepository pipelineRepo;
	private final PublishedSkillRepository publishedSkillRepo;
	private final PipelineBuilderService service;
	/** Phase 8-A-1d: forward execute/validate/preview to the Python sidecar
	 *  instead of the decommissioned :8001 backend. The sidecar already runs
	 *  the 27 BUILTIN_EXECUTORS in-process (block_runtime + pipeline_builder). */
	private final WebClient sidecarClient;

	public PipelineBuilderController(PipelineRepository pipelineRepo,
	                                 PublishedSkillRepository publishedSkillRepo,
	                                 PipelineBuilderService service,
	                                 WebClient pythonSidecarWebClient) {
		this.pipelineRepo = pipelineRepo;
		this.publishedSkillRepo = publishedSkillRepo;
		this.service = service;
		// Wrap the auto-configured sidecar client with a larger response
		// buffer — Pipeline executions can return big DataFrame previews.
		this.sidecarClient = pythonSidecarWebClient.mutate()
				.codecs(c -> c.defaultCodecs().maxInMemorySize(16 * 1024 * 1024))
				.build();
	}

	// ── Read-through repo aliases (kept here so the legacy path keeps shape) ──

	@GetMapping("/pipelines")
	public List<PipelineEntity> listPipelines(@RequestParam(required = false) String status) {
		return (status != null && !status.isBlank())
				? pipelineRepo.findByStatus(status) : pipelineRepo.findAll();
	}

	@GetMapping("/pipelines/{id}")
	public PipelineEntity getPipeline(@PathVariable Long id) {
		return pipelineRepo.findById(id).orElseThrow(() -> ApiException.notFound("pipeline"));
	}

	@GetMapping("/published-skills")
	public List<PublishedSkillEntity> listPublishedSkills(@RequestParam(required = false) String status) {
		return (status != null && !status.isBlank())
				? publishedSkillRepo.findByStatus(status) : publishedSkillRepo.findAll();
	}

	// ── Logic surfaces delegated to service ────────────────────────────────

	@GetMapping("/blocks")
	public List<Map<String, Object>> listBlocks() {
		return service.listBlocks();
	}

	@PostMapping("/published-skills/search")
	public List<PublishedSkillEntity> searchPublishedSkills(@RequestBody SearchRequest req) {
		String query = req == null ? null : req.query();
		Integer topK = req == null ? null : req.topK();
		return service.searchPublishedSkills(query, topK);
	}

	@GetMapping("/auto-check-rules")
	public List<Map<String, Object>> listAutoCheckRules() {
		return service.listAutoCheckRules();
	}

	public record SearchRequest(
			String query,
			@com.fasterxml.jackson.annotation.JsonProperty("top_k") Integer topK
	) {}

	// ── Sidecar forwards (pure HTTP transport) ─────────────────────────────

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

	/** Builder's RUN PREVIEW button needs this. The route was missed during
	 *  the cutover from fastapi-backend; without it the frontend got a
	 *  'Internal server error' from a 404-as-NoResourceFoundException. */
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
