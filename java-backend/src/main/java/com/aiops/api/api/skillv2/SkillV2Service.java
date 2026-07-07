package com.aiops.api.api.skillv2;

import com.aiops.api.common.ApiException;
import com.aiops.api.common.JsonUtils;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.skillv2.SkillV2Entity;
import com.aiops.api.domain.skillv2.SkillV2Repository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Skills v2 service. Phase 1 (this commit):
 * <ul>
 *   <li>list / get pass through to the repository</li>
 *   <li>{@link #compile} is a mock — returns the row's current pipeline_nodes
 *       (so the Editor's Re-compile loop works visually).</li>
 *   <li>{@link #saveSkill} accepts {nl, pipeline_nodes, in_type, out_type}
 *       and refreshes has_alarm derivation.</li>
 *   <li>{@link #saveAutomation} writes the role / trigger / gate / outcome
 *       block; validates that patrol needs has_alarm.</li>
 * </ul>
 *
 * <p>Phase 6+ replaces compile() with a real LLM call (Haiku via OpenRouter
 * per cost-control memory).
 */
@Service
public class SkillV2Service {

	private static final Set<String> VALID_ROLES   = Set.of("tool", "patrol", "datacheck");
	private static final Set<String> VALID_KINDS   = Set.of("schedule", "event");

	private final SkillV2Repository repo;
	private final PipelineRepository pipelineRepo;
	private final ObjectMapper mapper;
	private final com.aiops.api.domain.event.EventTypeRepository eventTypeRepo;

	public SkillV2Service(SkillV2Repository repo,
	                      PipelineRepository pipelineRepo,
	                      ObjectMapper mapper,
	                      com.aiops.api.domain.event.EventTypeRepository eventTypeRepo) {
		this.repo = repo;
		this.pipelineRepo = pipelineRepo;
		this.mapper = mapper;
		this.eventTypeRepo = eventTypeRepo;
	}

	// ─── Create ────────────────────────────────────────────────────────

	@Transactional
	public SkillDto create(Map<String, Object> body) {
		String slug = String.valueOf(body.getOrDefault("slug", "")).trim();
		String name = String.valueOf(body.getOrDefault("name", "")).trim();
		if (slug.isBlank()) throw ApiException.badRequest("slug is required");
		if (name.isBlank()) throw ApiException.badRequest("name is required");
		if (repo.findBySlug(slug).isPresent()) {
			throw ApiException.conflict("slug already exists: " + slug);
		}
		SkillV2Entity row = new SkillV2Entity();
		row.setSlug(slug);
		row.setName(name);
		row.setSub(String.valueOf(body.getOrDefault("sub", "")));
		row.setNl(String.valueOf(body.getOrDefault("nl", "")));
		row.setInType(String.valueOf(body.getOrDefault("in_type", "")));
		row.setOutType(String.valueOf(body.getOrDefault("out_type", "")));
		row.setPipelineNodes("[]");
		row.setHasAlarm(Boolean.FALSE);
		row.setRole("tool");
		row.setStatus("draft");
		return SkillDto.of(repo.save(row));
	}

	/**
	 * Cowork one-shot: create the pipeline, create the skill, and bind them
	 * in ONE transaction. Replaces the error-prone 3-call dance
	 * (save_pipeline → create_skill_v2 → bind_skill_pipeline) that left
	 * orphan pipelines in pb_pipelines when cowork stopped after step 1.
	 *
	 * <p>Skill lands as {@code status='draft'} — it is NOT active until the
	 * human opens the Editor and clicks 啟用. Body:
	 * {slug, name, sub?, nl?, pipeline_json (string), pipeline_kind?}.
	 */
	@Transactional
	public SkillFullDto createWithPipeline(Map<String, Object> body, Long callerUserId) {
		String slug = String.valueOf(body.getOrDefault("slug", "")).trim();
		String name = String.valueOf(body.getOrDefault("name", "")).trim();
		if (name.isBlank()) throw ApiException.badRequest("name is required");
		// 真 Skill 化 (2026-07-08): chat 的存為 Skill 不帶 slug — 從 name 衍生
		// （latent bug: 舊路徑直接 400）。碰撞時加序號。
		if (slug.isBlank()) {
			String base = name.toLowerCase().replaceAll("[^a-z0-9\\u4e00-\\u9fff]+", "-")
					.replaceAll("(^-|-$)", "");
			if (base.isBlank()) base = "skill";
			slug = base;
			int i = 2;
			while (repo.findBySlug(slug).isPresent()) slug = base + "-" + (i++);
		}
		if (repo.findBySlug(slug).isPresent()) {
			throw ApiException.conflict("slug already exists: " + slug);
		}
		Object pjObj = body.get("pipeline_json");
		if (pjObj == null) throw ApiException.badRequest("pipeline_json is required");
		String pipelineJson = (pjObj instanceof String s) ? s : JsonUtils.safeWrite(mapper, pjObj);
		if (pipelineJson == null || pipelineJson.isBlank()) {
			throw ApiException.badRequest("pipeline_json could not be serialized");
		}

		// 1. Create pipeline. Skills always map to kind='skill' unless overridden.
		PipelineEntity pipeline = new PipelineEntity();
		pipeline.setName(name);
		pipeline.setDescription("Cowork-built skill pipeline: " + name);
		pipeline.setPipelineKind(String.valueOf(body.getOrDefault("pipeline_kind", "skill")));
		pipeline.setPipelineJson(pipelineJson);
		pipeline.setCreatedBy(callerUserId);
		pipeline = pipelineRepo.save(pipeline);

		// 2. Create skill (draft, tool).
		SkillV2Entity row = new SkillV2Entity();
		row.setSlug(slug);
		row.setName(name);
		row.setSub(String.valueOf(body.getOrDefault("sub", "")));
		row.setNl(String.valueOf(body.getOrDefault("nl", "")));
		row.setPipelineNodes("[]");
		row.setHasAlarm(Boolean.FALSE);
		row.setRole("tool");
		row.setStatus("draft");
		Object docObj = body.get("doc");
		if (docObj != null) {
			String docJson = (docObj instanceof String ds) ? ds : JsonUtils.safeWrite(mapper, docObj);
			if (docJson != null && !docJson.isBlank()) row.setDoc(docJson);
		}
		row = repo.save(row);

		// 3. Bind (derives pipeline_nodes + has_alarm + in/out types).
		SkillDto bound = bindPipeline(slug, pipeline.getId());
		return new SkillFullDto(bound, pipelineJson);
	}

	/** 真 Skill 化 F4 (2026-07-08): 參數化精靈的更新出口 — 覆寫綁定 pipeline 的
	 *  pipeline_json（含 inputs 宣告與 $refs）與/或說明書 doc。 */
	public SkillDto updatePipelineAndDoc(String slug, Map<String, Object> body) {
		SkillV2Entity row = loadBySlug(slug);
		Object pjObj = body.get("pipeline_json");
		if (pjObj != null) {
			if (row.getPipelineId() == null) throw ApiException.badRequest("skill has no bound pipeline");
			PipelineEntity pipeline = pipelineRepo.findById(row.getPipelineId())
					.orElseThrow(() -> ApiException.notFound("pipeline " + row.getPipelineId()));
			String pipelineJson = (pjObj instanceof String s) ? s : JsonUtils.safeWrite(mapper, pjObj);
			if (pipelineJson == null || pipelineJson.isBlank()) {
				throw ApiException.badRequest("pipeline_json could not be serialized");
			}
			pipeline.setPipelineJson(pipelineJson);
			pipelineRepo.save(pipeline);
		}
		Object docObj = body.get("doc");
		if (docObj != null) {
			String docJson = (docObj instanceof String ds) ? ds : JsonUtils.safeWrite(mapper, docObj);
			row.setDoc(docJson);
		}
		row = repo.save(row);
		return SkillDto.of(row);
	}

	// ─── Read ──────────────────────────────────────────────────────────

	@Transactional(readOnly = true)
	public List<SkillDto> list() {
		return repo.findAll().stream()
				.sorted((a, b) -> {
					int byRole = Integer.compare(roleOrder(a.getRole()), roleOrder(b.getRole()));
					if (byRole != 0) return byRole;
					return a.getName().compareTo(b.getName());
				})
				.map(SkillDto::of).toList();
	}

	@Transactional(readOnly = true)
	public SkillDto get(String slug) {
		SkillV2Entity row = loadBySlug(slug);
		// Detail path (used by the Automate page) carries the tool_binding so
		// the UI can adapt the trigger scope to the pipeline's real state.
		ToolBindingDto binding = null;
		if (row.getPipelineId() != null) {
			PipelineEntity p = pipelineRepo.findById(row.getPipelineId()).orElse(null);
			if (p != null) binding = deriveToolBinding(p.getPipelineJson());
		}
		return SkillDto.of(row, binding);
	}

	/**
	 * Inspect the pipeline's data-source nodes to classify how {@code tool_id}
	 * is supplied — so an "all tools" automation isn't silently faked when the
	 * pipeline actually pins a single machine.
	 *
	 * <ul>
	 *   <li>PARAMETERIZED — a node uses {@code "$tool_id"} → fan-out injection works</li>
	 *   <li>PINNED — a node hardcodes a literal (e.g. "EQP-01") → only that tool</li>
	 *   <li>NONE — no node takes a tool_id → tool-agnostic</li>
	 *   <li>MIXED — inconsistent ($ref + literal, or two different literals)</li>
	 * </ul>
	 */
	ToolBindingDto deriveToolBinding(String pipelineJsonText) {
		boolean paramRef = false;
		java.util.Set<String> literals = new java.util.LinkedHashSet<>();
		for (Map<String, Object> node : extractDagNodes(pipelineJsonText)) {
			Object paramsObj = node.get("params");
			if (!(paramsObj instanceof Map<?, ?> params)) continue;
			Object tid = params.get("tool_id");
			if (tid == null) continue;
			String val = String.valueOf(tid).trim();
			if (val.isBlank()) continue;
			if (val.startsWith("$")) paramRef = true;
			else literals.add(val);
		}
		if (!paramRef && literals.isEmpty()) return new ToolBindingDto("NONE", null);
		if (paramRef && literals.isEmpty()) return new ToolBindingDto("PARAMETERIZED", null);
		if (!paramRef && literals.size() == 1) {
			return new ToolBindingDto("PINNED", literals.iterator().next());
		}
		return new ToolBindingDto("MIXED", null);  // $ + literal, or multi-literal
	}

	@Transactional(readOnly = true)
	public List<AlarmSourceDto> listAlarmSources(String excludeSlug) {
		List<AlarmSourceDto> out = new ArrayList<>();
		for (SkillV2Entity s : repo.findByRole("patrol")) {
			if (!Boolean.TRUE.equals(s.getHasAlarm())) continue;
			if (excludeSlug != null && excludeSlug.equals(s.getSlug())) continue;
			out.add(new AlarmSourceDto(s.getSlug(), s.getName(), s.getSub()));
		}
		return out;
	}

	/** Raw simulator event types an event-driven skill can subscribe to
	 *  ({"kind":"event","event":<name>}). Distinct from listAlarmSources,
	 *  which lists upstream patrol alarms. */
	@Transactional(readOnly = true)
	public List<EventTypeDto> listEventTypes() {
		List<EventTypeDto> out = new ArrayList<>();
		for (com.aiops.api.domain.event.EventTypeEntity e : eventTypeRepo.findAll()) {
			if (e.getName() == null || e.getName().isBlank()) continue;
			out.add(new EventTypeDto(e.getName(), e.getDescription()));
		}
		return out;
	}

	// ─── Compile (mock) ────────────────────────────────────────────────

	@Transactional(readOnly = true)
	public CompileResult compile(String slug, String nl) {
		SkillV2Entity row = loadBySlug(slug);
		// Phase 1 mock: return whatever is already on the row. Real LLM
		// compile lands in Phase 6.
		boolean hasAlarm = deriveHasAlarm(row.getPipelineNodes());
		return new CompileResult(row.getPipelineNodes(), hasAlarm, row.getInType(), row.getOutType());
	}

	// ─── Save skill ────────────────────────────────────────────────────

	@Transactional
	public SkillDto saveSkill(String slug, Map<String, Object> body) {
		SkillV2Entity row = loadBySlug(slug);
		if (body.containsKey("nl")) {
			row.setNl(String.valueOf(body.getOrDefault("nl", "")));
		}
		if (body.containsKey("pipeline_nodes")) {
			Object pn = body.get("pipeline_nodes");
			if (pn != null) {
				String pnStr = String.valueOf(pn);
				row.setPipelineNodes(pnStr);
				row.setHasAlarm(deriveHasAlarm(pnStr));
				// If the skill is currently a patrol but the pipeline lost
				// its verdict, demote to tool so the role stays truthful.
				if (!Boolean.TRUE.equals(row.getHasAlarm())
						&& "patrol".equals(row.getRole())) {
					row.setRole("tool");
					row.setTriggerConfig(null);
					row.setAlarmGate(null);
					row.setOutcome(null);
				}
			}
		}
		if (body.containsKey("in_type"))  row.setInType(String.valueOf(body.get("in_type")));
		if (body.containsKey("out_type")) row.setOutType(String.valueOf(body.get("out_type")));
		if (body.containsKey("name"))     row.setName(String.valueOf(body.get("name")));
		if (body.containsKey("sub"))      row.setSub(String.valueOf(body.get("sub")));
		return SkillDto.of(repo.save(row));
	}

	// ─── Save automation ──────────────────────────────────────────────

	@Transactional
	public SkillDto saveAutomation(String slug, Map<String, Object> body) {
		SkillV2Entity row = loadBySlug(slug);

		String role = body.containsKey("role")
				? String.valueOf(body.get("role")) : "tool";
		if (!VALID_ROLES.contains(role)) {
			throw ApiException.badRequest("invalid role: " + role);
		}
		if ("patrol".equals(role) && !Boolean.TRUE.equals(row.getHasAlarm())) {
			throw ApiException.badRequest(
					"pipeline 沒有 alarm 判斷式 — 無法升級為 Auto Patrol；請先在描述加入條件再重新編譯。");
		}

		// Trigger
		Object trig = body.get("trigger");
		String triggerJson = null;
		if (trig instanceof Map<?, ?> trigMapRaw) {
			@SuppressWarnings("unchecked")
			Map<String, Object> trigMap = new LinkedHashMap<>((Map<String, Object>) trigMapRaw);
			Object kind = trigMap.get("kind");
			if (kind == null || !VALID_KINDS.contains(String.valueOf(kind))) {
				throw ApiException.badRequest("trigger.kind must be schedule|event");
			}
			// Phase B: inject a deterministic schedule_spec the scheduler can
			// consume — the display `schedule` string ("每 1 小時") is for humans
			// only; the scheduler must NOT parse NL. Keep both.
			if ("schedule".equals(String.valueOf(kind))) {
				trigMap.put("schedule_spec",
						normalizeScheduleSpec(String.valueOf(trigMap.getOrDefault("schedule", ""))));
			}
			triggerJson = JsonUtils.safeWrite(mapper, trigMap);
		}
		row.setTriggerConfig(triggerJson);

		// Gate / outcome — patrol-only have content, datacheck = data only
		if ("patrol".equals(role)) {
			row.setAlarmGate(body.get("alarm_gate") == null ? null : String.valueOf(body.get("alarm_gate")));
			row.setOutcome(body.get("outcome") == null ? null : String.valueOf(body.get("outcome")));
		} else if ("datacheck".equals(role)) {
			row.setAlarmGate(null);
			row.setOutcome("data only");
		} else {  // tool
			row.setTriggerConfig(null);
			row.setAlarmGate(null);
			row.setOutcome(null);
		}

		row.setRole(role);
		return SkillDto.of(repo.save(row));
	}

	/**
	 * Map a display schedule string (one of the fixed SCHEDULES catalogue) into
	 * a deterministic spec the scheduler can act on without parsing NL.
	 * mode: "minutes" | "hourly" | "daily_at". Unknown → hourly/every=1.
	 */
	private static Map<String, Object> normalizeScheduleSpec(String display) {
		Map<String, Object> spec = new LinkedHashMap<>();
		String s = display == null ? "" : display.trim();
		switch (s) {
			case "每 30 分鐘" -> { spec.put("mode", "minutes"); spec.put("every", 30); }
			case "每 1 小時"  -> { spec.put("mode", "hourly");  spec.put("every", 1); }
			case "每 2 小時"  -> { spec.put("mode", "hourly");  spec.put("every", 2); }
			case "每日 08:00" -> { spec.put("mode", "daily_at"); spec.put("at_hour", 8); spec.put("at_minute", 0); }
			default -> { spec.put("mode", "hourly"); spec.put("every", 1); }
		}
		return spec;
	}

	@Transactional
	public SkillDto removeAutomation(String slug) {
		SkillV2Entity row = loadBySlug(slug);
		row.setRole("tool");
		row.setTriggerConfig(null);
		row.setAlarmGate(null);
		row.setOutcome(null);
		return SkillDto.of(repo.save(row));
	}

	@Transactional
	public void deleteSkill(String slug) {
		SkillV2Entity row = loadBySlug(slug);
		repo.delete(row);
	}

	// ─── Activation gate (draft → active) ──────────────────────────────

	/**
	 * Flip a skill from draft to active. This is the human's explicit
	 * "啟用" — only active skills will (eventually) be picked up by the
	 * scheduler. Tool-role skills don't need activation (they're run
	 * on-demand) but we allow it for uniformity.
	 */
	@Transactional
	public SkillDto activate(String slug) {
		SkillV2Entity row = loadBySlug(slug);
		row.setStatus("active");
		return SkillDto.of(repo.save(row));
	}

	/** Reverse: active → draft. Stops the skill being scheduled without
	 *  deleting it or stripping its automation config. */
	@Transactional
	public SkillDto deactivate(String slug) {
		SkillV2Entity row = loadBySlug(slug);
		row.setStatus("draft");
		return SkillDto.of(repo.save(row));
	}

	// ─── Cowork helpers (skill + pipeline one-shot, role pre-check) ──

	@Transactional(readOnly = true)
	public SkillFullDto getFull(String slug) {
		SkillV2Entity row = loadBySlug(slug);
		SkillDto skill = SkillDto.of(row);
		String pipelineJson = null;
		if (row.getPipelineId() != null) {
			PipelineEntity p = pipelineRepo.findById(row.getPipelineId()).orElse(null);
			if (p != null) pipelineJson = p.getPipelineJson();
		}
		return new SkillFullDto(skill, pipelineJson);
	}

	@Transactional(readOnly = true)
	public RoleReadinessDto checkRoleReadiness(String slug, String role) {
		if (role == null) return new RoleReadinessDto(false, "role is required");
		if (!VALID_ROLES.contains(role)) {
			return new RoleReadinessDto(false, "invalid role: " + role + " (valid: tool, patrol, datacheck)");
		}
		SkillV2Entity row = loadBySlug(slug);
		if (row.getPipelineId() == null) {
			return new RoleReadinessDto(false, "skill 沒有綁定 pipeline — 先呼 bind_skill_pipeline");
		}
		if ("patrol".equals(role) && !Boolean.TRUE.equals(row.getHasAlarm())) {
			return new RoleReadinessDto(false,
				"pipeline 沒有 alarm 判斷式（block_step_check 為 verdict node）— 無法升為 Auto Patrol。"
					+ "請先在 NL 加入觸發條件並重新編譯，或在 PB 手動加 block_step_check。");
		}
		return new RoleReadinessDto(true, null);
	}

	// ─── Bind pipeline (PB embed + cowork MCP) ────────────────────────

	/**
	 * Bind an existing pb_pipeline to this skill and project its nodes
	 * into the compact PipelineNode[] representation the v2 Editor renders.
	 *
	 * <p>Derivation rules:
	 * <ul>
	 *   <li>{@code k} — synthetic per-node label: IN for the first node,
	 *       S1/S2/S3… for transforms, ⚑ for a {@code block_step_check}
	 *       (the verdict).</li>
	 *   <li>{@code t} — block_id + a few headline params squeezed into one
	 *       line (good enough for v1; richer rendering can come later).</li>
	 *   <li>{@code s} — block_id as the secondary label.</li>
	 *   <li>{@code isVerdict} — true iff {@code block_step_check}.</li>
	 *   <li>{@code has_alarm} — true iff at least one verdict node exists.</li>
	 * </ul>
	 */
	@Transactional
	public SkillDto bindPipeline(String slug, Long pipelineId) {
		SkillV2Entity row = loadBySlug(slug);
		PipelineEntity pipeline = pipelineRepo.findById(pipelineId)
				.orElseThrow(() -> ApiException.notFound("pipeline " + pipelineId));

		List<Map<String, Object>> dagNodes = extractDagNodes(pipeline.getPipelineJson());
		List<Map<String, Object>> projected = new ArrayList<>(dagNodes.size());
		boolean hasVerdict = false;
		int transformIdx = 0;
		for (int i = 0; i < dagNodes.size(); i++) {
			Map<String, Object> node = dagNodes.get(i);
			String blockId = String.valueOf(node.getOrDefault("block_id", node.getOrDefault("block", "")));
			boolean verdict = "block_step_check".equalsIgnoreCase(blockId);
			if (verdict) hasVerdict = true;
			Map<String, Object> proj = new LinkedHashMap<>();
			proj.put("k", verdict ? "⚑" : (i == 0 ? "IN" : ("S" + (++transformIdx))));
			proj.put("t", summarizeNode(node, blockId));
			proj.put("s", blockId);
			if (verdict) proj.put("isVerdict", true);
			projected.add(proj);
		}

		String nodesJson = JsonUtils.safeWrite(mapper, projected);
		row.setPipelineId(pipelineId);
		row.setPipelineNodes(nodesJson != null ? nodesJson : "[]");
		row.setHasAlarm(hasVerdict);
		// Auto-derive in/out contract from the pipeline so the Editor
		// strip + Library card chips aren't empty after compile.
		row.setInType(deriveInType(pipeline.getPipelineJson()));
		row.setOutType(deriveOutType(dagNodes, hasVerdict));
		return SkillDto.of(repo.save(row));
	}

	@SuppressWarnings("unchecked")
	private String deriveInType(String pipelineJsonText) {
		if (pipelineJsonText == null || pipelineJsonText.isBlank()) return "";
		Map<String, Object> root = JsonUtils.parseObject(mapper, pipelineJsonText);
		Object inputsObj = root.get("inputs");
		if (inputsObj instanceof List<?> inputs && !inputs.isEmpty()) {
			List<String> labels = new ArrayList<>();
			for (Object in : inputs) {
				if (in instanceof Map<?, ?> m) {
					Object name = ((Map<String, Object>) m).get("name");
					if (name != null && !String.valueOf(name).isBlank()) {
						labels.add(String.valueOf(name));
					}
				}
			}
			if (!labels.isEmpty()) return String.join(", ", labels);
		}
		// Fallback: pull a hint from the IN node's first non-blank param
		// (covers older pipelines that bake the input as a literal param).
		Object nodes = root.get("nodes");
		if (nodes instanceof List<?> list && !list.isEmpty() && list.get(0) instanceof Map<?, ?> n0) {
			Object params = ((Map<String, Object>) n0).get("params");
			if (params instanceof Map<?, ?> pm) {
				for (Map.Entry<?, ?> e : ((Map<String, Object>) pm).entrySet()) {
					String v = String.valueOf(e.getValue());
					if (!v.isBlank() && !"null".equals(v)) {
						return String.valueOf(e.getKey());
					}
				}
			}
		}
		return "—";
	}

	private String deriveOutType(List<Map<String, Object>> dagNodes, boolean hasVerdict) {
		if (hasVerdict) return "alarm (pass/fail) + 摘要";
		if (dagNodes.isEmpty()) return "—";
		Map<String, Object> last = dagNodes.get(dagNodes.size() - 1);
		String blockId = String.valueOf(last.getOrDefault("block_id", "")).toLowerCase();
		if (blockId.contains("data_view") || blockId.contains("table")) return "table";
		if (blockId.contains("chart") || blockId.contains("plot")
				|| blockId.contains("heatmap") || blockId.contains("trend")) return "chart";
		if (blockId.contains("step_check")) return "pass/fail";
		return "value";
	}

	@SuppressWarnings("unchecked")
	private List<Map<String, Object>> extractDagNodes(String pipelineJsonText) {
		if (pipelineJsonText == null || pipelineJsonText.isBlank()) return List.of();
		Map<String, Object> root = JsonUtils.parseObject(mapper, pipelineJsonText);
		Object nodes = root.get("nodes");
		if (nodes instanceof List<?> list) {
			List<Map<String, Object>> out = new ArrayList<>(list.size());
			for (Object n : list) {
				if (n instanceof Map<?, ?>) out.add((Map<String, Object>) n);
			}
			return out;
		}
		return List.of();
	}

	@SuppressWarnings("unchecked")
	private String summarizeNode(Map<String, Object> node, String blockId) {
		Object paramsObj = node.get("params");
		if (paramsObj instanceof Map<?, ?> params) {
			StringBuilder sb = new StringBuilder(blockId);
			int keys = 0;
			for (Map.Entry<?, ?> e : ((Map<String, Object>) params).entrySet()) {
				if (keys >= 2) break;  // keep one-line label tidy
				Object v = e.getValue();
				if (v == null) continue;
				String val = String.valueOf(v);
				if (val.length() > 24) val = val.substring(0, 24) + "…";
				sb.append(keys == 0 ? " · " : ", ");
				sb.append(e.getKey()).append("=").append(val);
				keys++;
			}
			return sb.toString();
		}
		return blockId;
	}

	// ─── Helpers ───────────────────────────────────────────────────────

	/**
	 * Resolve a path segment that may be a numeric id OR a slug. Auto-generated
	 * slugs always end in a random alphanumeric tail and never look like a bare
	 * integer, so a pure-digit segment is unambiguously an id. This lets every
	 * /api/v2/skills/{key}/** endpoint accept ids — the UI uses /skills/<id>
	 * URLs (slugs are an internal detail the human never sees).
	 */
	private SkillV2Entity loadBySlug(String key) {
		if (key != null && key.matches("\\d+")) {
			return repo.findById(Long.valueOf(key))
					.orElseThrow(() -> ApiException.notFound("skill v2"));
		}
		return repo.findBySlug(key)
				.orElseThrow(() -> ApiException.notFound("skill v2"));
	}

	private boolean deriveHasAlarm(String pipelineNodesJson) {
		List<Map<String, Object>> nodes = JsonUtils.parseListOfObjects(mapper, pipelineNodesJson);
		for (Map<String, Object> n : nodes) {
			Object iv = n.get("isVerdict");
			if (Boolean.TRUE.equals(iv) || "true".equals(String.valueOf(iv))) return true;
		}
		return false;
	}

	private static int roleOrder(String role) {
		// patrol first (alarms matter most), then datacheck, then tool.
		return switch (role) {
			case "patrol" -> 0;
			case "datacheck" -> 1;
			default -> 2;
		};
	}

	// ─── DTOs ──────────────────────────────────────────────────────────

	/** How the bound pipeline supplies tool_id. See {@link #deriveToolBinding}. */
	public record ToolBindingDto(String state, String pinnedTool) {}

	public record SkillDto(
			Long id, String slug, String name, String sub,
			String nl, Long pipelineId, String pipelineNodes,
			Boolean hasAlarm, String inType, String outType,
			String role, String triggerConfig, String alarmGate, String outcome,
			String status, String testCases, String doc, ToolBindingDto toolBinding
	) {
		static SkillDto of(SkillV2Entity e) {
			return of(e, null);
		}

		static SkillDto of(SkillV2Entity e, ToolBindingDto toolBinding) {
			return new SkillDto(
					e.getId(), e.getSlug(), e.getName(), e.getSub(),
					e.getNl(), e.getPipelineId(), e.getPipelineNodes(),
					e.getHasAlarm(), e.getInType(), e.getOutType(),
					e.getRole(), e.getTriggerConfig(), e.getAlarmGate(), e.getOutcome(),
					e.getStatus(), e.getTestCases(), e.getDoc(), toolBinding
			);
		}
	}

	public record CompileResult(String pipelineNodes, Boolean hasAlarm,
	                             String inType, String outType) {}

	public record AlarmSourceDto(String slug, String name, String sub) {}

	public record EventTypeDto(String name, String description) {}

	public record SkillFullDto(SkillDto skill, String pipelineJson) {}

	public record RoleReadinessDto(boolean ok, String reason) {}
}
