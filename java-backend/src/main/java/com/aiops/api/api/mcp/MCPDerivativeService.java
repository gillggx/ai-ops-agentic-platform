package com.aiops.api.api.mcp;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.JsonUtils;
import com.aiops.api.domain.mcp.McpDefinitionEntity;
import com.aiops.api.domain.mcp.McpDefinitionRepository;
import com.aiops.api.domain.pipeline.BlockEntity;
import com.aiops.api.domain.pipeline.BlockRepository;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.pipeline.PublishedSkillEntity;
import com.aiops.api.domain.pipeline.PublishedSkillRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * MCPDerivativeService — orchestrates the creation of derivative artefacts
 * (pb_blocks + pb_pipelines + pb_published_skills) when a System MCP is
 * created with {@code produces_block} / {@code produces_skill} flags.
 *
 * <p>The flow:
 * <ol>
 *   <li>Caller (controller) hands over a fully validated CreateRequest +
 *       optional BlockDraft / SkillDraft (the LLM-generated content, already
 *       reviewed by the user in the form).</li>
 *   <li>This service inserts MCP, then conditionally inserts block + pipeline
 *       + published skill in the same transaction. Failure rolls all back —
 *       MCP without its derivatives is a known broken state.</li>
 *   <li>Derivative rows are tagged {@code source='mcp_auto'} and
 *       {@code source_mcp_id=mcp.id} so they can be distinguished from the
 *       27 hand-crafted blocks and the seeded skills.</li>
 * </ol>
 *
 * <p>Why a separate service (vs. inline in controller): atomic write spans
 * four repositories. The controller stays HTTP-thin per Phase 12 OOP
 * convention.
 */
@Service
public class MCPDerivativeService {

	private static final Logger log = LoggerFactory.getLogger(MCPDerivativeService.class);

	private static final String SOURCE_MCP_AUTO = "mcp_auto";
	private static final String DEFAULT_VERSION = "1.0.0";

	private final McpDefinitionRepository mcpRepo;
	private final BlockRepository blockRepo;
	private final PipelineRepository pipelineRepo;
	private final PublishedSkillRepository skillRepo;
	private final ObjectMapper mapper;

	public MCPDerivativeService(McpDefinitionRepository mcpRepo,
	                            BlockRepository blockRepo,
	                            PipelineRepository pipelineRepo,
	                            PublishedSkillRepository skillRepo,
	                            ObjectMapper mapper) {
		this.mcpRepo = mcpRepo;
		this.blockRepo = blockRepo;
		this.pipelineRepo = pipelineRepo;
		this.skillRepo = skillRepo;
		this.mapper = mapper;
	}

	/**
	 * Atomically create an MCP, plus optional derivative Block + Pipeline + PublishedSkill.
	 *
	 * @throws ApiException CONFLICT if name collides, BAD_REQUEST if produces_skill
	 *                      is requested without produces_block (skill needs a block).
	 */
	@Transactional
	public McpDefinitionEntity createWithDerivatives(CreateMcpWithDerivativesRequest req,
	                                                 AuthPrincipal caller) {
		validateRequest(req);
		if (mcpRepo.findByName(req.name()).isPresent()) {
			throw ApiException.conflict("mcp name already exists");
		}

		McpDefinitionEntity mcp = mcpRepo.save(buildMcp(req));
		final Long mcpId = mcp.getId();

		if (Boolean.TRUE.equals(req.producesBlock())) {
			BlockEntity block = buildAutoBlock(mcp, req.blockDraft(), caller);
			blockRepo.save(block);
			log.info("MCP {} (id={}) auto-generated block {} (source=mcp_auto)",
					mcp.getName(), mcpId, block.getName());

			if (Boolean.TRUE.equals(req.producesSkill())) {
				PipelineEntity pipeline = buildOneBlockPipeline(mcp, block, req.skillDraft(), caller);
				pipeline = pipelineRepo.save(pipeline);
				PublishedSkillEntity skill = buildAutoSkill(mcp, pipeline, req.skillDraft());
				skillRepo.save(skill);
				log.info("MCP {} (id={}) auto-generated skill slug={} (pipeline_id={})",
						mcp.getName(), mcpId, skill.getSlug(), pipeline.getId());
			}
		}

		return mcp;
	}

	// ─── Validation ─────────────────────────────────────────────────────

	private void validateRequest(CreateMcpWithDerivativesRequest req) {
		if (req.producesSkill() != null && req.producesSkill()
				&& !(req.producesBlock() != null && req.producesBlock())) {
			throw ApiException.badRequest(
					"produces_skill=true requires produces_block=true (skill wraps a block)");
		}
		if (Boolean.TRUE.equals(req.producesBlock()) && req.blockDraft() == null) {
			throw ApiException.badRequest(
					"produces_block=true requires block_draft in payload");
		}
		if (Boolean.TRUE.equals(req.producesSkill()) && req.skillDraft() == null) {
			throw ApiException.badRequest(
					"produces_skill=true requires skill_draft in payload");
		}
	}

	// ─── Builders ───────────────────────────────────────────────────────

	private McpDefinitionEntity buildMcp(CreateMcpWithDerivativesRequest req) {
		McpDefinitionEntity e = new McpDefinitionEntity();
		e.setName(req.name());
		if (req.description() != null) e.setDescription(req.description());
		e.setMcpType(req.mcpType() != null ? req.mcpType() : "system");
		if (req.apiConfig() != null) e.setApiConfig(req.apiConfig());
		if (req.inputSchema() != null) e.setInputSchema(req.inputSchema());
		if (req.outputSchema() != null) e.setOutputSchema(req.outputSchema());
		if (req.visibility() != null) e.setVisibility(req.visibility());
		e.setProducesBlock(Boolean.TRUE.equals(req.producesBlock()));
		e.setProducesSkill(Boolean.TRUE.equals(req.producesSkill()));
		if (req.generationMeta() != null) e.setBlockGenerationMeta(req.generationMeta());
		return e;
	}

	private BlockEntity buildAutoBlock(McpDefinitionEntity mcp,
	                                   BlockDraft draft,
	                                   AuthPrincipal caller) {
		BlockEntity b = new BlockEntity();
		b.setName(draft.blockName() != null && !draft.blockName().isBlank()
				? draft.blockName()
				: "block_mcp_" + mcp.getName());
		b.setVersion(DEFAULT_VERSION);
		b.setCategory("source");  // MCP-derived blocks always fetch from external (= source)
		b.setStatus("active");
		b.setDescription(nullToEmpty(draft.description()));
		b.setInputSchema("[]");  // source block: no upstream inputs
		b.setOutputSchema(safeJson(List.of(
				Map.of("port", "data", "type", "dataframe",
				       "description", "MCP response flattened to dataframe rows")
		)));
		b.setParamSchema(nullToBraces(draft.paramSchema()));
		// Implementation tells sidecar's BlockRegistry to dispatch via the
		// shared McpProxyBlockExecutor (Phase B), reading mcp_name at runtime.
		Map<String, Object> impl = new LinkedHashMap<>();
		impl.put("type", "mcp_proxy");
		impl.put("mcp_name", mcp.getName());
		impl.put("delegate_block", "block_mcp_call");
		b.setImplementation(safeJson(impl));
		b.setExamples(nullToBrackets(draft.examples()));
		b.setOutputColumnsHint(nullToBrackets(draft.outputColumnsHint()));
		b.setIsCustom(Boolean.FALSE);
		if (caller != null) b.setCreatedBy(caller.userId());
		b.setSource(SOURCE_MCP_AUTO);
		b.setSourceMcpId(mcp.getId());
		return b;
	}

	private PipelineEntity buildOneBlockPipeline(McpDefinitionEntity mcp,
	                                             BlockEntity block,
	                                             SkillDraft draft,
	                                             AuthPrincipal caller) {
		PipelineEntity p = new PipelineEntity();
		p.setName("auto-skill-" + mcp.getName());
		p.setDescription("Auto-generated skill pipeline wrapping MCP " + mcp.getName());
		p.setStatus("active");
		p.setVersion(DEFAULT_VERSION);
		// Single-block DAG: skill produces dataframe rows from the MCP call.
		Map<String, Object> node = new LinkedHashMap<>();
		node.put("id", "n1");
		node.put("block", block.getName());
		node.put("version", DEFAULT_VERSION);
		node.put("params", draft.defaultParams() != null
				? JsonUtils.parseObject(mapper, draft.defaultParams())
				: Map.of());
		Map<String, Object> dag = Map.of("nodes", List.of(node), "edges", List.of());
		p.setPipelineJson(safeJson(dag));
		if (caller != null) p.setCreatedBy(caller.userId());
		return p;
	}

	private PublishedSkillEntity buildAutoSkill(McpDefinitionEntity mcp,
	                                            PipelineEntity pipeline,
	                                            SkillDraft draft) {
		PublishedSkillEntity s = new PublishedSkillEntity();
		s.setPipelineId(pipeline.getId());
		s.setPipelineVersion(DEFAULT_VERSION);
		s.setSlug(slugify(draft.slug() != null ? draft.slug() : "mcp-" + mcp.getName()));
		s.setName(draft.name() != null ? draft.name() : mcp.getName());
		s.setUseCase(nullToEmpty(draft.useCase()));
		s.setWhenToUse(nullToBrackets(draft.whenToUse()));
		s.setInputsSchema(nullToBrackets(draft.inputsSchema()));
		s.setOutputsSchema(nullToBraces(draft.outputsSchema()));
		s.setTags(nullToBrackets(draft.tags()));
		s.setStatus("active");
		s.setSource(SOURCE_MCP_AUTO);
		s.setSourceMcpId(mcp.getId());
		return s;
	}

	// ─── Helpers ────────────────────────────────────────────────────────

	private static String nullToEmpty(String s) { return s == null ? "" : s; }
	private static String nullToBraces(String s) { return (s == null || s.isBlank()) ? "{}" : s; }
	private static String nullToBrackets(String s) { return (s == null || s.isBlank()) ? "[]" : s; }

	private String safeJson(Object o) {
		String s = JsonUtils.safeWrite(mapper, o);
		return s != null ? s : "{}";
	}

	private static String slugify(String input) {
		String s = input.toLowerCase().replaceAll("[^a-z0-9-]", "-").replaceAll("-+", "-");
		return s.replaceAll("^-|-$", "");
	}

	/** Build the audit metadata JSON to stash on the MCP. */
	public static String buildGenerationMeta(String llmModel, String promptVersion) {
		String now = OffsetDateTime.now().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME);
		Map<String, Object> meta = new LinkedHashMap<>();
		meta.put("llm_model", llmModel);
		meta.put("prompt_version", promptVersion);
		meta.put("generated_at", now);
		meta.put("last_regenerated_at", now);
		try {
			return new ObjectMapper().writeValueAsString(meta);
		} catch (com.fasterxml.jackson.core.JsonProcessingException e) {
			return null;
		}
	}

	// ─── Request DTOs ───────────────────────────────────────────────────

	/** Top-level request for the {@code POST /api/v1/mcp-definitions} endpoint
	 *  when produces_block / produces_skill toggles are involved. */
	public record CreateMcpWithDerivativesRequest(
			String name,
			String description,
			String mcpType,
			String apiConfig,
			String inputSchema,
			String outputSchema,
			String visibility,
			Boolean producesBlock,
			Boolean producesSkill,
			String generationMeta,
			BlockDraft blockDraft,
			SkillDraft skillDraft
	) {}

	public record BlockDraft(
			String blockName,
			String description,
			String paramSchema,      // JSON text
			String examples,         // JSON text (list)
			String outputColumnsHint // JSON text (list)
	) {}

	public record SkillDraft(
			String slug,
			String name,
			String useCase,
			String whenToUse,        // JSON text (list)
			String inputsSchema,     // JSON text (list)
			String outputsSchema,    // JSON text (object)
			String tags,             // JSON text (list)
			String defaultParams     // JSON text (object) — node n1 params on the wrapping pipeline
	) {}
}
