package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.mcp.McpDefinitionEntity;
import com.aiops.api.domain.mcp.McpDefinitionRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/** MCP catalog — fed into LangGraph prompt so the LLM can pick tools. */
@RestController
@RequestMapping("/internal/mcp-definitions")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalMcpController {

	private final McpDefinitionRepository repository;

	public InternalMcpController(McpDefinitionRepository repository) {
		this.repository = repository;
	}

	@GetMapping
	public ApiResponse<List<Dto>> list(@RequestParam(required = false) String mcpType) {
		var all = (mcpType != null && !mcpType.isBlank())
				? repository.findByMcpType(mcpType) : repository.findAll();
		return ApiResponse.ok(all.stream().map(Dto::of).toList());
	}

	public record Dto(Long id, String name, String description, String mcpType, String apiConfig,
	                  String inputSchema, String outputSchema, Long systemMcpId,
	                  String processingIntent, String processingScript, String visibility) {
		static Dto of(McpDefinitionEntity e) {
			return new Dto(e.getId(), e.getName(), e.getDescription(), e.getMcpType(),
					e.getApiConfig(), e.getInputSchema(), e.getOutputSchema(),
					e.getSystemMcpId(), e.getProcessingIntent(), e.getProcessingScript(),
					e.getVisibility());
		}
	}
}
