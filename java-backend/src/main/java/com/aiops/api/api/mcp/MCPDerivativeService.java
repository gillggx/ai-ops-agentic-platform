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
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

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

	/**
	 * P1-6 (2026-06-04) — atomically replace an existing MCP's derivative
	 * Block (+ Skill if present) using freshly LLM-regenerated drafts.
	 *
	 * <p>In-place: same {@code pb_blocks.id} and {@code pb_published_skills.id}
	 * are kept so any pipeline that already references them keeps working.
	 * Only the schema/spec columns are overwritten. Old generation meta
	 * (model + prompt_version + timestamps) is pushed onto a
	 * {@code history[]} array inside {@code block_generation_meta} for audit.
	 *
	 * @throws ApiException NOT_FOUND if MCP missing or no derivative row to
	 *         update (sanity guard — caller should only invoke this when
	 *         {@code produces_block=true}).
	 */
	@Transactional
	public McpDefinitionEntity regenerateDerivatives(Long mcpId,
	                                                 BlockDraft blockDraft,
	                                                 SkillDraft skillDraft,
	                                                 String newGenerationMeta,
	                                                 AuthPrincipal caller) {
		McpDefinitionEntity mcp = mcpRepo.findById(mcpId)
				.orElseThrow(() -> ApiException.notFound("mcp definition"));
		if (!Boolean.TRUE.equals(mcp.getProducesBlock())) {
			throw ApiException.badRequest(
					"MCP " + mcp.getName() + " does not produce derivatives — nothing to regenerate");
		}
		if (blockDraft == null) {
			throw ApiException.badRequest("blockDraft is required for regenerate");
		}

		BlockEntity block = blockRepo
				.findFirstBySourceMcpIdAndSource(mcpId, SOURCE_MCP_AUTO)
				.orElseThrow(() -> ApiException.notFound(
						"derivative block for mcp " + mcp.getName() + " missing — re-create instead"));
		applyBlockDraft(block, blockDraft);
		blockRepo.save(block);
		log.info("MCP {} (id={}) regenerated block {} in-place (block_id={})",
				mcp.getName(), mcpId, block.getName(), block.getId());

		if (Boolean.TRUE.equals(mcp.getProducesSkill())) {
			if (skillDraft == null) {
				throw ApiException.badRequest("skillDraft is required when produces_skill=true");
			}
			PublishedSkillEntity skill = skillRepo
					.findFirstBySourceMcpIdAndSource(mcpId, SOURCE_MCP_AUTO)
					.orElseThrow(() -> ApiException.notFound(
							"derivative skill for mcp " + mcp.getName() + " missing — re-create instead"));
			applySkillDraft(skill, skillDraft);
			skillRepo.save(skill);
			log.info("MCP {} (id={}) regenerated skill slug={} in-place (skill_id={})",
					mcp.getName(), mcpId, skill.getSlug(), skill.getId());
		}

		// Push old meta onto history[] before overwriting (audit trail).
		mcp.setBlockGenerationMeta(mergeMetaWithHistory(mcp.getBlockGenerationMeta(), newGenerationMeta));
		mcpRepo.save(mcp);
		return mcp;
	}

	/**
	 * Compute derivative status for a single MCP. Used by GET DTO mapping so
	 * the admin UI knows whether to show the stale warning + regenerate CTA.
	 *
	 * <p>{@code is_stale} fires when the MCP row's updated_at is meaningfully
	 * (+2s tolerance) ahead of the last_regenerated_at recorded in
	 * block_generation_meta. The tolerance absorbs Hibernate
	 * {@code @UpdateTimestamp} vs DB clock jitter so newly-created MCPs
	 * don't immediately look stale.
	 */
	public DerivativeStatus derivativeStatusOf(McpDefinitionEntity mcp) {
		boolean producesBlock = Boolean.TRUE.equals(mcp.getProducesBlock());
		boolean producesSkill = Boolean.TRUE.equals(mcp.getProducesSkill());
		if (!producesBlock && !producesSkill) {
			return null;
		}

		Optional<BlockEntity> blk = blockRepo
				.findFirstBySourceMcpIdAndSource(mcp.getId(), SOURCE_MCP_AUTO);
		Optional<PublishedSkillEntity> skl = producesSkill
				? skillRepo.findFirstBySourceMcpIdAndSource(mcp.getId(), SOURCE_MCP_AUTO)
				: Optional.empty();

		String lastRegen = readLastRegeneratedAt(mcp.getBlockGenerationMeta());
		boolean isStale = computeIsStale(mcp.getUpdatedAt(), lastRegen);

		return new DerivativeStatus(
				isStale,
				lastRegen,
				blk.isPresent(),
				producesSkill ? skl.isPresent() : null,
				blk.map(BlockEntity::getId).orElse(null),
				blk.map(BlockEntity::getName).orElse(null),
				skl.map(PublishedSkillEntity::getId).orElse(null),
				skl.map(PublishedSkillEntity::getSlug).orElse(null)
		);
	}

	private boolean computeIsStale(OffsetDateTime updatedAt, String lastRegenIso) {
		if (lastRegenIso == null || lastRegenIso.isBlank()) return true;
		if (updatedAt == null) return false;
		try {
			OffsetDateTime lastRegen = OffsetDateTime.parse(lastRegenIso);
			return updatedAt.isAfter(lastRegen.plusSeconds(2));
		} catch (RuntimeException e) {
			log.warn("malformed last_regenerated_at '{}' — treating as stale", lastRegenIso);
			return true;
		}
	}

	@SuppressWarnings("unchecked")
	private String readLastRegeneratedAt(String metaJson) {
		if (metaJson == null || metaJson.isBlank()) return null;
		try {
			Map<String, Object> meta = mapper.readValue(metaJson, Map.class);
			Object v = meta.get("last_regenerated_at");
			return v == null ? null : v.toString();
		} catch (RuntimeException | java.io.IOException e) {
			return null;
		}
	}

	/**
	 * Pop the old top-level entry into history[] and replace top-level with
	 * the new generation meta. New meta is expected to be a JSON object with
	 * {llm_model, prompt_version, generated_at, last_regenerated_at}.
	 */
	@SuppressWarnings("unchecked")
	private String mergeMetaWithHistory(String oldMetaJson, String newMetaJson) {
		Map<String, Object> newMeta;
		try {
			newMeta = newMetaJson == null || newMetaJson.isBlank()
					? new LinkedHashMap<>()
					: mapper.readValue(newMetaJson, Map.class);
		} catch (RuntimeException | java.io.IOException e) {
			newMeta = new LinkedHashMap<>();
		}

		List<Object> history = new ArrayList<>();
		if (oldMetaJson != null && !oldMetaJson.isBlank()) {
			try {
				Map<String, Object> oldMeta = mapper.readValue(oldMetaJson, Map.class);
				Object existing = oldMeta.remove("history");
				if (existing instanceof List<?> el) history.addAll((List<Object>) el);
				if (!oldMeta.isEmpty()) history.add(oldMeta);
			} catch (RuntimeException | java.io.IOException e) {
				log.warn("ignoring malformed old block_generation_meta: {}", e.getMessage());
			}
		}
		// Cap history to last 10 entries so the column doesn't bloat unbounded.
		if (history.size() > 10) {
			history = history.subList(history.size() - 10, history.size());
		}
		newMeta.put("history", history);
		return safeJson(newMeta);
	}

	private void applyBlockDraft(BlockEntity block, BlockDraft draft) {
		if (draft.blockName() != null && !draft.blockName().isBlank()) {
			// Block name is a stable id used by pipelines — only rewrite when
			// the user explicitly typed a new one in the form. Most regenerates
			// keep the original.
			block.setName(draft.blockName());
		}
		block.setDescription(nullToEmpty(draft.description()));
		block.setParamSchema(nullToBraces(draft.paramSchema()));
		block.setExamples(nullToBrackets(draft.examples()));
		block.setOutputColumnsHint(nullToBrackets(draft.outputColumnsHint()));
	}

	private void applySkillDraft(PublishedSkillEntity skill, SkillDraft draft) {
		if (draft.name() != null) skill.setName(draft.name());
		skill.setUseCase(nullToEmpty(draft.useCase()));
		skill.setWhenToUse(nullToBrackets(draft.whenToUse()));
		skill.setInputsSchema(nullToBrackets(draft.inputsSchema()));
		skill.setOutputsSchema(nullToBraces(draft.outputsSchema()));
		skill.setTags(nullToBrackets(draft.tags()));
		// slug is identity — keep stable across regenerates.
	}

	/** Snapshot of an MCP's derivative artefacts for the GET DTO. */
	public record DerivativeStatus(
			Boolean isStale,
			String lastRegeneratedAt,
			Boolean hasBlock,
			Boolean hasSkill,
			Long blockId,
			String blockName,
			Long skillId,
			String skillSlug
	) {}

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
