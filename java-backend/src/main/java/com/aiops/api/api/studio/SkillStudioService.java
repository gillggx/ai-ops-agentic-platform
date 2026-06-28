package com.aiops.api.api.studio;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.JsonUtils;
import com.aiops.api.domain.skill.SkillDocumentEntity;
import com.aiops.api.domain.skill.SkillDocumentRepository;
import com.aiops.api.domain.skill.SkillStageEntity;
import com.aiops.api.domain.skill.SkillStageRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Skill Studio service — orchestrates the 3-stage editor (画面 A) and the
 * Checklist Editor (画面 B). Owns {@link SkillStageEntity} lifecycle:
 * lazy-create on first read, edit prose, compile to rules, activate.
 *
 * <p>Phase 2 (this commit): compile is a deterministic stub that returns
 * canned rules per kind so the frontend can be built end-to-end. Phase 5
 * swaps in a real LLM call (Haiku via OpenRouter — per memory
 * {@code feedback_cost_control_llm}) without any wire-format change.
 */
@Service
public class SkillStudioService {

	private static final List<String> KIND_ORDER = List.of("detect", "diagnose", "recover");
	private static final Set<String> VALID_KINDS = Set.of("detect", "diagnose", "recover");

	private final SkillStageRepository stageRepo;
	private final SkillDocumentRepository skillRepo;
	private final ObjectMapper mapper;

	public SkillStudioService(SkillStageRepository stageRepo,
	                          SkillDocumentRepository skillRepo,
	                          ObjectMapper mapper) {
		this.stageRepo = stageRepo;
		this.skillRepo = skillRepo;
		this.mapper = mapper;
	}

	// ─── Read ──────────────────────────────────────────────────────────

	/**
	 * Return all three stages of a skill, in canonical order. Lazily creates
	 * empty rows for any kind that doesn't have one yet so the UI never has
	 * to handle "no detect row" — it always gets exactly three.
	 */
	@Transactional
	public List<StageDto> listStages(String slug) {
		SkillDocumentEntity skill = skillRepo.findBySlug(slug)
				.orElseThrow(() -> ApiException.notFound("skill"));
		List<SkillStageEntity> existing = stageRepo.findBySkillDocId(skill.getId());

		Map<String, SkillStageEntity> byKind = new HashMap<>();
		for (SkillStageEntity s : existing) byKind.put(s.getKind(), s);

		List<StageDto> out = new ArrayList<>(3);
		for (String kind : KIND_ORDER) {
			SkillStageEntity row = byKind.get(kind);
			if (row == null) row = createEmptyStage(skill.getId(), kind);
			out.add(StageDto.of(row));
		}
		return out;
	}

	private SkillStageEntity createEmptyStage(Long skillDocId, String kind) {
		SkillStageEntity s = new SkillStageEntity();
		s.setSkillDocId(skillDocId);
		s.setKind(kind);
		s.setProse(defaultProseFor(kind));
		s.setCompiledRules("[]");
		s.setStatus("draft");
		s.setVersion("0.1");
		return stageRepo.save(s);
	}

	// ─── Save ──────────────────────────────────────────────────────────

	@Transactional
	public StageDto saveStage(String slug, String kind, Map<String, Object> body) {
		validateKind(kind);
		SkillStageEntity row = loadStage(slug, kind);
		if ("stable".equals(row.getStatus())) {
			throw ApiException.conflict(
					"stage is stable — deactivate before editing (Phase 7: revert flow)");
		}
		if (body.containsKey("prose")) {
			row.setProse(String.valueOf(body.getOrDefault("prose", "")));
		}
		if (body.containsKey("trigger_config")) {
			row.setTriggerConfig(String.valueOf(body.getOrDefault("trigger_config", "{}")));
		}
		if (body.containsKey("pipeline_id")) {
			Object pid = body.get("pipeline_id");
			row.setPipelineId(pid == null ? null : ((Number) pid).longValue());
		}
		return StageDto.of(stageRepo.save(row));
	}

	// ─── Compile (Phase 2 stub) ────────────────────────────────────────

	/**
	 * Phase 2 mock compile: returns canned rules per kind so the UI can be
	 * built end-to-end. Phase 5 replaces the body of this method with an
	 * LLM call; the {@link CompileResult} shape stays identical.
	 *
	 * <p>The stub doesn't mutate the DB — caller is expected to call
	 * {@link #saveStage} with the returned rules JSON if it wants to
	 * persist them. This matches the "Re-compile (preview)" flow in the
	 * design where the user reviews compile output before saving.
	 */
	@Transactional(readOnly = true)
	public CompileResult compileStage(String slug, String kind, String prose) {
		validateKind(kind);
		// Confirm the skill exists so callers get 404 before bothering the LLM.
		skillRepo.findBySlug(slug).orElseThrow(() -> ApiException.notFound("skill"));

		List<Map<String, Object>> rules = stubRules(kind);
		String rulesJson = JsonUtils.safeWrite(mapper, rules);
		Map<String, Object> meta = new HashMap<>();
		meta.put("compiler", "stub-v0");
		meta.put("prose_chars", prose == null ? 0 : prose.length());
		return new CompileResult(rulesJson != null ? rulesJson : "[]", meta);
	}

	// ─── Activate ──────────────────────────────────────────────────────

	@Transactional
	public StageDto activateStage(String slug, String kind, AuthPrincipal caller) {
		validateKind(kind);
		SkillStageEntity row = loadStage(slug, kind);
		if (row.getCompiledRules() == null || row.getCompiledRules().isBlank()
				|| "[]".equals(row.getCompiledRules().trim())) {
			throw ApiException.badRequest("compile prose first — compiled_rules is empty");
		}
		row.setStatus("stable");
		row.setActivatedAt(OffsetDateTime.now());
		if (caller != null) row.setActivatedBy(caller.userId());
		bumpMinorVersion(row);
		return StageDto.of(stageRepo.save(row));
	}

	private void bumpMinorVersion(SkillStageEntity row) {
		String v = row.getVersion() == null ? "0.1" : row.getVersion();
		try {
			String[] parts = v.split("\\.", 2);
			int major = Integer.parseInt(parts[0]);
			int minor = parts.length > 1 ? Integer.parseInt(parts[1]) : 0;
			row.setVersion(major + "." + (minor + 1));
		} catch (NumberFormatException e) {
			row.setVersion("0.1");
		}
	}

	// ─── Helpers ───────────────────────────────────────────────────────

	private SkillStageEntity loadStage(String slug, String kind) {
		SkillDocumentEntity skill = skillRepo.findBySlug(slug)
				.orElseThrow(() -> ApiException.notFound("skill"));
		return stageRepo.findBySkillDocIdAndKind(skill.getId(), kind)
				.orElseGet(() -> createEmptyStage(skill.getId(), kind));
	}

	private void validateKind(String kind) {
		if (!VALID_KINDS.contains(kind)) {
			throw ApiException.badRequest("invalid kind: " + kind + "; must be detect|diagnose|recover");
		}
	}

	// ─── Stub canned rules ─────────────────────────────────────────────

	private static List<Map<String, Object>> stubRules(String kind) {
		switch (kind) {
			case "detect": return List.of(
					Map.of("id", "D1",
							"when", "排程 every 1h",
							"for", "所有機台",
							"if", "count(spc_status==OOC, last 5) ≥ 2",
							"then", "emit Event{tool, lot, ts, severity}")
			);
			case "diagnose": return List.of(
					row("A1", "Tool",   "Tool 角度：過去 48h 各機台 OOC 次數長條 (>=10 標記)", 10),
					row("A2", "Lot",    "Lot 角度：過去 48h 各 lot OOC 次數長條 (任一 lot >=2 標記)", 2),
					row("A3", "APC",    "APC 角度：過去 48h 各 APC OOC 次數長條 (任一 APC >=2 標記)", 2),
					row("A4", "Recipe", "Recipe 角度：過去 48h 各 recipe OOC 次數長條 (任一 recipe >=2 標記)", 2),
					row("A5", "Step",   "Step 角度：過去 48h 各站點 OOC 次數長條 (任一站點 >=2 標記)", 2)
			);
			case "recover": return List.of(
					recover("P1", "APC 飽和 ∧ SPC 上飄",   "Hold lot · 通知 owner",    "approval"),
					recover("P2", "recipe ≥3 機台 OOC",     "凍結 recipe · 開 CR",       "approval"),
					recover("P3", "Tool OOC ≥100/48h",      "自動建維修工單",            "auto"),
					recover("P4", "單機台偶發 · 其他正常", "僅記錄，不告警",            "notify")
			);
			default: return List.of();
		}
	}

	private static Map<String, Object> row(String id, String dim, String title, int threshold) {
		Map<String, Object> m = new HashMap<>();
		m.put("id", id);
		m.put("dim", dim);
		m.put("title", title);
		m.put("operator", ">=");
		m.put("threshold", threshold);
		return m;
	}

	private static Map<String, Object> recover(String id, String pattern, String action, String safety) {
		Map<String, Object> m = new HashMap<>();
		m.put("id", id);
		m.put("pattern", pattern);
		m.put("action", action);
		m.put("safety", safety);
		return m;
	}

	private static String defaultProseFor(String kind) {
		switch (kind) {
			case "detect":   return "每 1 小時，掃所有機台。最近 5 筆 SPC 紀錄中若 ≥2 筆 OOC，emit Event。";
			case "diagnose": return "事件發生時要從 5 個角度檢查：Tool / Lot / APC / Recipe / Step。每個維度過 48 小時 OOC 次數超過門檻就標記為 Finding。";
			case "recover":  return "依 Findings 命中的 pattern 決定行動：APC 飽和 + SPC 上飄要 Hold lot；Tool 過量 OOC 自動建維修工單；單機台偶發只記錄不告警。";
			default: return "";
		}
	}

	// ─── DTOs ──────────────────────────────────────────────────────────

	public record StageDto(
			Long id, Long skillDocId, String kind,
			String triggerConfig, String prose, String compiledRules,
			Long pipelineId, String status, String version,
			OffsetDateTime activatedAt, Long activatedBy,
			OffsetDateTime createdAt, OffsetDateTime updatedAt
	) {
		static StageDto of(SkillStageEntity e) {
			return new StageDto(
					e.getId(), e.getSkillDocId(), e.getKind(),
					e.getTriggerConfig(), e.getProse(), e.getCompiledRules(),
					e.getPipelineId(), e.getStatus(), e.getVersion(),
					e.getActivatedAt(), e.getActivatedBy(),
					e.getCreatedAt(), e.getUpdatedAt()
			);
		}
	}

	public record CompileResult(String compiledRules, Map<String, Object> meta) {}
}
