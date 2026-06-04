package com.aiops.api.api.mcp;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.mcp.McpDefinitionEntity;
import com.aiops.api.domain.mcp.McpDefinitionRepository;
import jakarta.validation.constraints.NotBlank;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/mcp-definitions")
public class McpDefinitionController {

	private final McpDefinitionRepository repository;
	private final MCPDerivativeService derivativeService;
	private final MCPGenerationProxy generationProxy;

	public McpDefinitionController(McpDefinitionRepository repository,
	                               MCPDerivativeService derivativeService,
	                               MCPGenerationProxy generationProxy) {
		this.repository = repository;
		this.derivativeService = derivativeService;
		this.generationProxy = generationProxy;
	}

	@GetMapping
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<Dtos.Summary>> list(@RequestParam(required = false) String mcpType) {
		List<McpDefinitionEntity> all = (mcpType != null && !mcpType.isBlank())
				? repository.findByMcpType(mcpType) : repository.findAll();
		return ApiResponse.ok(all.stream().map(Dtos::summaryOf).toList());
	}

	@GetMapping("/{id}")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Dtos.Detail> get(@PathVariable Long id) {
		return ApiResponse.ok(Dtos.detailOf(repository.findById(id)
				.orElseThrow(() -> ApiException.notFound("mcp definition"))));
	}

	@PostMapping
	@Transactional
	@PreAuthorize(Authorities.ADMIN)  // only IT_ADMIN creates MCPs per SPEC §2.6.2
	public ApiResponse<Dtos.Detail> create(@Validated @RequestBody Dtos.CreateRequest req,
	                                       @AuthenticationPrincipal AuthPrincipal caller) {
		// V54: when produces_block / produces_skill flags are present, route
		// through the derivative service so MCP + block + pipeline + skill
		// are inserted atomically. Falls back to plain MCP insert otherwise.
		if (Boolean.TRUE.equals(req.producesBlock()) || Boolean.TRUE.equals(req.producesSkill())) {
			MCPDerivativeService.CreateMcpWithDerivativesRequest dreq =
					new MCPDerivativeService.CreateMcpWithDerivativesRequest(
							req.name(), req.description(), req.mcpType(),
							req.apiConfig(), req.inputSchema(), req.outputSchema(),
							req.visibility(),
							req.producesBlock(), req.producesSkill(),
							req.generationMeta(),
							req.blockDraft(), req.skillDraft());
			return ApiResponse.ok(Dtos.detailOf(derivativeService.createWithDerivatives(dreq, caller)));
		}

		if (repository.findByName(req.name()).isPresent()) {
			throw ApiException.conflict("mcp name already exists");
		}
		McpDefinitionEntity e = new McpDefinitionEntity();
		e.setName(req.name());
		if (req.description() != null) e.setDescription(req.description());
		if (req.mcpType() != null) e.setMcpType(req.mcpType());
		if (req.apiConfig() != null) e.setApiConfig(req.apiConfig());
		if (req.inputSchema() != null) e.setInputSchema(req.inputSchema());
		if (req.outputSchema() != null) e.setOutputSchema(req.outputSchema());
		if (req.systemMcpId() != null) e.setSystemMcpId(req.systemMcpId());
		if (req.processingIntent() != null) e.setProcessingIntent(req.processingIntent());
		if (req.processingScript() != null) e.setProcessingScript(req.processingScript());
		if (req.visibility() != null) e.setVisibility(req.visibility());
		return ApiResponse.ok(Dtos.detailOf(repository.save(e)));
	}

	/**
	 * V54: LLM-generate block + skill drafts from MCP description.
	 *
	 * <p>Two modes:
	 * <ul>
	 *   <li>{@code id == null} — generate for an in-progress form (the MCP
	 *       hasn't been persisted yet). Payload carries the draft MCP
	 *       description / input_schema directly.</li>
	 *   <li>{@code id != null} — regenerate for an existing MCP (after the
	 *       user edited its description). The Java side loads the row and
	 *       hands it to the sidecar.</li>
	 * </ul>
	 *
	 * <p>The sidecar runs Claude Haiku 4.5 (per spec §2.5 decision) with a
	 * structured JSON prompt and returns
	 * {@code {block_draft, skill_draft, lint_issues, llm_model, tokens}}.
	 * No DB writes happen here — the user reviews and edits in the form
	 * before the atomic {@code POST /} commits everything.
	 */
	@PostMapping("/generate-derivatives")
	@PreAuthorize(Authorities.ADMIN)
	public ApiResponse<Map<String, Object>> generateDerivatives(
			@Validated @RequestBody Dtos.GenerateRequest req,
			@AuthenticationPrincipal AuthPrincipal caller) {
		return ApiResponse.ok(generationProxy.generate(req, caller));
	}

	@PutMapping("/{id}")
	@Transactional
	@PreAuthorize(Authorities.ADMIN)
	public ApiResponse<Dtos.Detail> update(@PathVariable Long id,
	                                       @Validated @RequestBody Dtos.UpdateRequest req) {
		McpDefinitionEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("mcp definition"));
		if (req.description() != null) e.setDescription(req.description());
		if (req.apiConfig() != null) e.setApiConfig(req.apiConfig());
		if (req.inputSchema() != null) e.setInputSchema(req.inputSchema());
		if (req.outputSchema() != null) e.setOutputSchema(req.outputSchema());
		if (req.processingIntent() != null) e.setProcessingIntent(req.processingIntent());
		if (req.processingScript() != null) e.setProcessingScript(req.processingScript());
		if (req.preferOverSystem() != null) e.setPreferOverSystem(req.preferOverSystem());
		if (req.visibility() != null) e.setVisibility(req.visibility());
		return ApiResponse.ok(Dtos.detailOf(repository.save(e)));
	}

	@DeleteMapping("/{id}")
	@Transactional
	@PreAuthorize(Authorities.ADMIN)
	public ApiResponse<Void> delete(@PathVariable Long id) {
		if (!repository.existsById(id)) throw ApiException.notFound("mcp definition");
		repository.deleteById(id);
		return ApiResponse.ok(null);
	}

	@GetMapping("/catalog")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<java.util.List<Dtos.Detail>> catalog() {
		return ApiResponse.ok(repository.findAll().stream().map(Dtos::detailOf).toList());
	}

	public static final class Dtos {

		public record Summary(Long id, String name, String description, String mcpType,
		                      String visibility, Boolean preferOverSystem,
		                      java.time.OffsetDateTime updatedAt) {}

		public record Detail(Long id, String name, String description, String mcpType,
		                     String apiConfig, String inputSchema, String outputSchema,
		                     Long systemMcpId, String processingIntent, String processingScript,
		                     String uiRenderConfig, String inputDefinition, String sampleOutput,
		                     Boolean preferOverSystem, String visibility,
		                     java.time.OffsetDateTime createdAt, java.time.OffsetDateTime updatedAt) {}

		public record CreateRequest(@NotBlank String name, String description, String mcpType,
		                            String apiConfig, String inputSchema, String outputSchema,
		                            Long systemMcpId, String processingIntent, String processingScript,
		                            String visibility,
		                            // V54: optional derivative payload — when produces_block / produces_skill
		                            // are true, block_draft / skill_draft carry the LLM-reviewed content
		                            // for atomic insert. Frontend obtains the drafts via the
		                            // POST /generate-derivatives endpoint first.
		                            Boolean producesBlock, Boolean producesSkill,
		                            String generationMeta,
		                            MCPDerivativeService.BlockDraft blockDraft,
		                            MCPDerivativeService.SkillDraft skillDraft) {}

		public record UpdateRequest(String description, String apiConfig, String inputSchema,
		                            String outputSchema, String processingIntent,
		                            String processingScript, Boolean preferOverSystem,
		                            String visibility) {}

		/** V54: payload for LLM derivative generation. */
		public record GenerateRequest(
				/** Existing MCP id to regenerate against. Null = generate for a draft (unsaved) MCP. */
				Long mcpId,
				/** Required when mcpId is null. */
				String name,
				String description,
				String inputSchema,
				String outputSchema,
				String apiConfig,
				/** Which derivatives to generate. Defaults: both true. */
				Boolean wantBlock,
				Boolean wantSkill) {}

		static Summary summaryOf(McpDefinitionEntity e) {
			return new Summary(e.getId(), e.getName(), e.getDescription(), e.getMcpType(),
					e.getVisibility(), e.getPreferOverSystem(), e.getUpdatedAt());
		}

		static Detail detailOf(McpDefinitionEntity e) {
			return new Detail(e.getId(), e.getName(), e.getDescription(), e.getMcpType(),
					e.getApiConfig(), e.getInputSchema(), e.getOutputSchema(), e.getSystemMcpId(),
					e.getProcessingIntent(), e.getProcessingScript(), e.getUiRenderConfig(),
					e.getInputDefinition(), e.getSampleOutput(), e.getPreferOverSystem(),
					e.getVisibility(), e.getCreatedAt(), e.getUpdatedAt());
		}
	}
}
