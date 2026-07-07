package com.aiops.api.api.pipeline;

import com.aiops.api.domain.pipeline.BlockEntity;
import com.aiops.api.domain.pipeline.BlockRepository;
import com.aiops.api.domain.pipeline.PipelineAutoCheckTriggerEntity;
import com.aiops.api.domain.pipeline.PipelineAutoCheckTriggerRepository;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.pipeline.PublishedSkillEntity;
import com.aiops.api.domain.pipeline.PublishedSkillRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * Business logic for {@link PipelineBuilderController}.
 *
 * <p>Extracted 2026-05-23 as part of the Phase 12 OOP refactor. The
 * controller is mostly a path-parity alias (frontend still calls
 * {@code /api/v1/pipeline-builder/*} after the cutover from the
 * decommissioned Python backend); the genuine domain logic — block JSON
 * column parsing, naive substring search ranking over published skills,
 * and the auto-check binding join — lives here.
 *
 * <p>Sidecar forwards ({@code /execute}, {@code /validate}, {@code /preview})
 * stay in the controller because they're pure HTTP transport with no
 * business state.
 */
@Service
public class PipelineBuilderService {

	private static final int DEFAULT_TOP_K = 5;
	private static final int MAX_TOP_K = 50;

	private final PipelineRepository pipelineRepo;
	private final BlockRepository blockRepo;
	private final PublishedSkillRepository publishedSkillRepo;
	private final PipelineAutoCheckTriggerRepository autoCheckRepo;
	private final com.aiops.api.domain.skillv2.SkillV2Repository skillV2Repo;
	private final ObjectMapper mapper;

	public PipelineBuilderService(PipelineRepository pipelineRepo,
	                              BlockRepository blockRepo,
	                              PublishedSkillRepository publishedSkillRepo,
	                              PipelineAutoCheckTriggerRepository autoCheckRepo,
	                              com.aiops.api.domain.skillv2.SkillV2Repository skillV2Repo,
	                              ObjectMapper mapper) {
		this.pipelineRepo = pipelineRepo;
		this.blockRepo = blockRepo;
		this.publishedSkillRepo = publishedSkillRepo;
		this.autoCheckRepo = autoCheckRepo;
		this.skillV2Repo = skillV2Repo;
		this.mapper = mapper;
	}

	// ── Blocks ─────────────────────────────────────────────────────────────

	/** All blocks with JSON columns parsed into arrays/objects for
	 *  frontend consumption. */
	public List<Map<String, Object>> listBlocks() {
		return blockRepo.findAll().stream().map(this::blockDto).toList();
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

	/** Parse a text column that stores JSON; return original string on parse error. */
	private Object parseJsonOrRaw(String raw) {
		if (raw == null || raw.isBlank()) return null;
		try { return mapper.readTree(raw); }
		catch (JsonProcessingException e) { return raw; }
	}

	// ── Published-skill search ─────────────────────────────────────────────

	/**
	 * Keyword search across active published skills — used by the LLM agent's
	 * {@code search_published_skills} tool. Simple case-insensitive substring
	 * scoring across name / use_case / when_to_use / tags / slug.
	 *
	 * <p>Ranking is intentionally naive (count substring matches across
	 * fields) since the registry is small (typically &lt; 50 active skills)
	 * and pgvector embeddings haven't been wired yet. Empty query → top-K
	 * alphabetical by name.
	 */
	public List<PublishedSkillEntity> searchPublishedSkills(String query, Integer topK) {
		final String q = (query == null) ? "" : query.trim().toLowerCase();
		final int safeTopK = (topK == null || topK <= 0) ? DEFAULT_TOP_K : Math.min(topK, MAX_TOP_K);

		// Union the two skill registries:
		//   - pb_published_skills (legacy + V54 mcp_auto derivatives)
		//   - skills_v2 (the new Skill=1-pipeline model; only status='active'
		//     so drafts aren't auto-invoked by chat). Projected into transient
		//     PublishedSkillEntity so the response shape + sidecar invoke path
		//     (slug → pipeline_id → execute) stay unchanged.
		// Dedupe by pipeline_id, skills_v2 winning (newer model).
		List<PublishedSkillEntity> pool = new java.util.ArrayList<>(publishedSkillRepo.findByStatus("active"));
		java.util.Set<Long> seenPids = new java.util.HashSet<>();
		for (PublishedSkillEntity s : pool) {
			if (s.getPipelineId() != null) seenPids.add(s.getPipelineId());
		}
		List<PublishedSkillEntity> v2 = new java.util.ArrayList<>();
		for (com.aiops.api.domain.skillv2.SkillV2Entity sk : skillV2Repo.findByStatusOrderByNameAsc("active")) {
			if (sk.getPipelineId() == null) continue;            // unbound → not runnable
			if (seenPids.contains(sk.getPipelineId())) continue; // already covered by pb_published
			v2.add(projectSkillV2(sk));
		}
		// skills_v2 first so dedupe/ranking ties favour the new model.
		List<PublishedSkillEntity> active = new java.util.ArrayList<>(v2);
		active.addAll(pool);

		if (q.isEmpty()) {
			return active.stream()
					.sorted((a, b) -> a.getName().compareToIgnoreCase(b.getName()))
					.limit(safeTopK)
					.toList();
		}

		final String[] terms = q.split("\\s+");
		return active.stream()
				.map(skill -> Map.entry(skill, scoreSkill(skill, terms)))
				.filter(e -> e.getValue() > 0)
				.sorted((a, b) -> Integer.compare(b.getValue(), a.getValue()))
				.limit(safeTopK)
				.map(Map.Entry::getKey)
				.toList();
	}

	/** Project a skills_v2 row into a transient PublishedSkillEntity so chat's
	 *  search/invoke path can treat both registries uniformly. NOT persisted. */
	private PublishedSkillEntity projectSkillV2(com.aiops.api.domain.skillv2.SkillV2Entity sk) {
		PublishedSkillEntity e = new PublishedSkillEntity();
		e.setSlug(sk.getSlug());
		e.setName(sk.getName());
		e.setUseCase(sk.getSub() == null ? "" : sk.getSub());
		e.setWhenToUse(sk.getNl() == null ? "" : sk.getNl());  // nl is the rich, searchable description
		e.setPipelineId(sk.getPipelineId());
		e.setStatus("active");
		e.setSource("skill_v2");
		// 真 Skill 化 (2026-07-08): doc（人審過的說明書）優先於 sub/nl；
		// inputs_schema 直接取綁定 pipeline 的 inputs 宣告 — agent 據此帶參數。
		if (sk.getDoc() != null && !sk.getDoc().isBlank()) {
			Map<String, Object> doc = JsonUtils.parseObject(mapper, sk.getDoc());
			Object uc = doc.get("use_case");
			if (uc instanceof String u && !u.isBlank()) e.setUseCase(u);
			Object wtu = doc.get("when_to_use");
			if (wtu != null) {
				String w = JsonUtils.safeWrite(mapper, wtu);
				if (w != null) e.setWhenToUse(w);
			}
			Object tags = doc.get("tags");
			if (tags != null) {
				String t = JsonUtils.safeWrite(mapper, tags);
				if (t != null) e.setTags(t);
			}
			Object ex = doc.get("example_invocation");
			if (ex != null) {
				String x = JsonUtils.safeWrite(mapper, ex);
				if (x != null) e.setExampleInvocation(x);
			}
		}
		if (sk.getPipelineId() != null) {
			pipelineRepo.findById(sk.getPipelineId()).ifPresent(pl -> {
				Map<String, Object> pj = JsonUtils.parseObject(mapper, pl.getPipelineJson());
				Object inputs = pj.get("inputs");
				if (inputs instanceof java.util.List<?> l && !l.isEmpty()) {
					String is = JsonUtils.safeWrite(mapper, inputs);
					if (is != null) e.setInputsSchema(is);
				}
			});
		}
		return e;
	}

	private static int scoreSkill(PublishedSkillEntity s, String[] terms) {
		String hay = (
				(s.getName() == null ? "" : s.getName()) + " " +
				(s.getUseCase() == null ? "" : s.getUseCase()) + " " +
				(s.getWhenToUse() == null ? "" : s.getWhenToUse()) + " " +
				(s.getTags() == null ? "" : s.getTags()) + " " +
				(s.getSlug() == null ? "" : s.getSlug())
		).toLowerCase();
		int score = 0;
		for (String t : terms) {
			if (t.isBlank()) continue;
			int idx = 0;
			while ((idx = hay.indexOf(t, idx)) >= 0) {
				score++;
				idx += t.length();
			}
		}
		return score;
	}

	// ── Auto-check rules join ──────────────────────────────────────────────

	/** Auto-check trigger rows enriched with their pipeline's name + status
	 *  so the Frontend Auto-Check Rules page can render bindings without a
	 *  per-row N+1 fetch. */
	public List<Map<String, Object>> listAutoCheckRules() {
		List<PipelineAutoCheckTriggerEntity> triggers = autoCheckRepo.findAll();
		if (triggers.isEmpty()) return List.of();

		// Bulk fetch referenced pipelines for name+status lookup.
		List<Long> pipelineIds = triggers.stream()
				.map(PipelineAutoCheckTriggerEntity::getPipelineId).toList();
		Map<Long, PipelineEntity> pipelines = pipelineRepo.findAllById(pipelineIds).stream()
				.collect(Collectors.toMap(PipelineEntity::getId, p -> p));
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
}
import com.aiops.api.common.JsonUtils;
