package com.aiops.api.api.skillv2;

import com.aiops.api.common.ApiException;
import com.aiops.api.common.JsonUtils;
import com.aiops.api.domain.skillv2.SkillV2Entity;
import com.aiops.api.domain.skillv2.SkillV2Repository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
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
	private final ObjectMapper mapper;

	public SkillV2Service(SkillV2Repository repo, ObjectMapper mapper) {
		this.repo = repo;
		this.mapper = mapper;
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
		return SkillDto.of(loadBySlug(slug));
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
		if (trig instanceof Map<?, ?> trigMap) {
			Object kind = trigMap.get("kind");
			if (kind == null || !VALID_KINDS.contains(String.valueOf(kind))) {
				throw ApiException.badRequest("trigger.kind must be schedule|event");
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

	@Transactional
	public SkillDto removeAutomation(String slug) {
		SkillV2Entity row = loadBySlug(slug);
		row.setRole("tool");
		row.setTriggerConfig(null);
		row.setAlarmGate(null);
		row.setOutcome(null);
		return SkillDto.of(repo.save(row));
	}

	// ─── Helpers ───────────────────────────────────────────────────────

	private SkillV2Entity loadBySlug(String slug) {
		return repo.findBySlug(slug)
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

	public record SkillDto(
			Long id, String slug, String name, String sub,
			String nl, Long pipelineId, String pipelineNodes,
			Boolean hasAlarm, String inType, String outType,
			String role, String triggerConfig, String alarmGate, String outcome,
			String status, String testCases
	) {
		static SkillDto of(SkillV2Entity e) {
			return new SkillDto(
					e.getId(), e.getSlug(), e.getName(), e.getSub(),
					e.getNl(), e.getPipelineId(), e.getPipelineNodes(),
					e.getHasAlarm(), e.getInType(), e.getOutType(),
					e.getRole(), e.getTriggerConfig(), e.getAlarmGate(), e.getOutcome(),
					e.getStatus(), e.getTestCases()
			);
		}
	}

	public record CompileResult(String pipelineNodes, Boolean hasAlarm,
	                             String inType, String outType) {}

	public record AlarmSourceDto(String slug, String name, String sub) {}
}
