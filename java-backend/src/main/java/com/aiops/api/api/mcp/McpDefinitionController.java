package com.aiops.api.api.mcp;

import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.mcp.McpDefinitionEntity;
import com.aiops.api.domain.mcp.McpDefinitionRepository;
import jakarta.validation.constraints.NotBlank;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1/mcp-definitions")
public class McpDefinitionController {

	private final McpDefinitionRepository repository;

	public McpDefinitionController(McpDefinitionRepository repository) {
		this.repository = repository;
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
	public ApiResponse<Dtos.Detail> create(@Validated @RequestBody Dtos.CreateRequest req) {
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
		                            String visibility) {}

		public record UpdateRequest(String description, String apiConfig, String inputSchema,
		                            String outputSchema, String processingIntent,
		                            String processingScript, Boolean preferOverSystem,
		                            String visibility) {}

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
