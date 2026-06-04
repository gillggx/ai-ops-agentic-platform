package com.aiops.api.api.mcp;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.common.ApiException;
import com.aiops.api.domain.mcp.McpDefinitionEntity;
import com.aiops.api.domain.mcp.McpDefinitionRepository;
import com.aiops.api.sidecar.PythonSidecarClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Proxy for the sidecar's {@code POST /internal/mcp/generate-derivatives}
 * endpoint. Resolves the MCP context (either from request payload or by
 * loading the existing row), forwards to the sidecar, and returns the
 * untouched draft response to the controller.
 *
 * <p>Kept separate from {@link MCPDerivativeService} because this owns
 * sidecar I/O (network + reactive {@link reactor.core.publisher.Mono}) — the
 * derivative service is pure DB and stays free of WebClient dependencies.
 */
@Service
public class MCPGenerationProxy {

	private static final Logger log = LoggerFactory.getLogger(MCPGenerationProxy.class);

	private static final String SIDECAR_PATH = "/internal/mcp/generate-derivatives";
	private static final Duration TIMEOUT = Duration.ofSeconds(45);  // Haiku 4.5 is fast but allow margin

	private final PythonSidecarClient sidecar;
	private final McpDefinitionRepository mcpRepo;

	public MCPGenerationProxy(PythonSidecarClient sidecar, McpDefinitionRepository mcpRepo) {
		this.sidecar = sidecar;
		this.mcpRepo = mcpRepo;
	}

	@SuppressWarnings("unchecked")
	public Map<String, Object> generate(McpDefinitionController.Dtos.GenerateRequest req,
	                                    AuthPrincipal caller) {
		Map<String, Object> body = buildSidecarPayload(req);

		try {
			Map<String, Object> resp = sidecar
					.postJson(SIDECAR_PATH, body, Map.class, caller)
					.block(TIMEOUT);
			if (resp == null) {
				throw ApiException.serviceUnavailable("sidecar returned empty response");
			}
			return resp;
		} catch (RuntimeException e) {
			log.warn("MCP derivative generation failed for name={}: {}",
					body.get("name"), e.getMessage());
			throw ApiException.serviceUnavailable(
					"LLM derivative generation failed: " + e.getMessage());
		}
	}

	private Map<String, Object> buildSidecarPayload(McpDefinitionController.Dtos.GenerateRequest req) {
		Map<String, Object> payload = new LinkedHashMap<>();

		if (req.mcpId() != null) {
			McpDefinitionEntity mcp = mcpRepo.findById(req.mcpId())
					.orElseThrow(() -> ApiException.notFound("mcp definition"));
			payload.put("mcp_id", mcp.getId());
			payload.put("name", mcp.getName());
			payload.put("description", mcp.getDescription());
			payload.put("input_schema", mcp.getInputSchema());
			payload.put("output_schema", mcp.getOutputSchema());
			payload.put("api_config", mcp.getApiConfig());
		} else {
			if (req.name() == null || req.name().isBlank()) {
				throw ApiException.badRequest("name is required when mcpId is not provided");
			}
			if (req.description() == null || req.description().isBlank()) {
				throw ApiException.badRequest("description is required for LLM generation");
			}
			payload.put("name", req.name());
			payload.put("description", req.description());
			payload.put("input_schema", req.inputSchema());
			payload.put("output_schema", req.outputSchema());
			payload.put("api_config", req.apiConfig());
		}
		payload.put("want_block", req.wantBlock() == null ? Boolean.TRUE : req.wantBlock());
		payload.put("want_skill", req.wantSkill() == null ? Boolean.TRUE : req.wantSkill());
		return payload;
	}
}
