package com.aiops.api.api.skillv2;

import com.aiops.api.common.JsonUtils;
import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.skill.SkillRunEntity;
import com.aiops.api.domain.skill.SkillRunRepository;
import com.aiops.api.domain.skillv2.SkillV2Entity;
import com.aiops.api.domain.skillv2.SkillV2Repository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

/**
 * Executes a skills_v2 skill: runs its bound pipeline via the sidecar, reads
 * the block_step_check verdict, and (for patrol skills) writes an alarm when
 * the verdict trips — otherwise records why it was skipped. Every run writes a
 * {@code skill_runs} row keyed by {@code skill_v2_id} so the patrol-activity
 * funnel can trace event → run → alarm for the new model.
 *
 * <p>Replaces the legacy step-based SkillRunnerService for the v2 model:
 * 1 skill = 1 pipeline, no multi-step materialisation.
 */
@Service
public class SkillV2RunnerService {

	private static final Logger log = LoggerFactory.getLogger(SkillV2RunnerService.class);

	private final SkillV2Repository skillRepo;
	private final PipelineRepository pipelineRepo;
	private final SkillRunRepository runRepo;
	private final AlarmRepository alarmRepo;
	private final WebClient sidecar;
	private final ObjectMapper mapper;

	public SkillV2RunnerService(SkillV2Repository skillRepo,
	                            PipelineRepository pipelineRepo,
	                            SkillRunRepository runRepo,
	                            AlarmRepository alarmRepo,
	                            WebClient pythonSidecarWebClient,
	                            ObjectMapper mapper) {
		this.skillRepo = skillRepo;
		this.pipelineRepo = pipelineRepo;
		this.runRepo = runRepo;
		this.alarmRepo = alarmRepo;
		this.sidecar = pythonSidecarWebClient;
		this.mapper = mapper;
	}

	/**
	 * Run a v2 skill end-to-end. Returns {ok, skill_run_id, status,
	 * verdict, alarm_id?}. Synchronous — callers (scheduler / internal
	 * endpoint) run it on their own thread.
	 */
	@Transactional
	public Map<String, Object> runSystem(Long skillV2Id, String triggeredBy, Map<String, Object> payload) {
		SkillV2Entity sk = skillRepo.findById(skillV2Id).orElse(null);
		if (sk == null) {
			return Map.of("ok", false, "error", "skill_v2 " + skillV2Id + " not found");
		}
		Map<String, Object> inputs = payload != null ? payload : Map.of();

		SkillRunEntity run = new SkillRunEntity();
		run.setSkillV2Id(skillV2Id);
		run.setTriggeredAt(OffsetDateTime.now());
		run.setTriggeredBy(triggeredBy == null || triggeredBy.isBlank() ? "system" : triggeredBy);
		run.setTriggerPayload(JsonUtils.safeWrite(mapper, inputs));
		run.setIsTest(false);
		run.setStatus("running");
		run = runRepo.save(run);

		long t0 = System.currentTimeMillis();
		Boolean verdict = null;
		Map<String, Object> check = null;
		Long alarmId = null;
		try {
			if (sk.getPipelineId() == null) {
				throw new RuntimeException("skill has no bound pipeline");
			}
			PipelineEntity pipe = pipelineRepo.findById(sk.getPipelineId())
					.orElseThrow(() -> new RuntimeException("pipeline " + sk.getPipelineId() + " missing"));
			Map<String, Object> pj = JsonUtils.parseObject(mapper, pipe.getPipelineJson());

			Map<String, Object> body = Map.of(
					"pipeline_json", pj,
					"inputs", inputs,
					"triggered_by", "system_skill_v2");
			@SuppressWarnings("unchecked")
			Map<String, Object> result = sidecar.post()
					.uri("/internal/pipeline/execute")
					.header("Content-Type", "application/json")
					.bodyValue(body)
					.retrieve()
					.bodyToMono(Map.class)
					.block();

			check = extractCheck(result);
			verdict = check == null ? null : asBool(check.get("pass"));
			run.setStepResults(JsonUtils.safeWrite(mapper, summarise(result, verdict, check)));
			run.setStatus("success");

			// Alarm decision — only patrol skills with a verdict node emit.
			if ("patrol".equals(sk.getRole()) && Boolean.TRUE.equals(sk.getHasAlarm())) {
				if (Boolean.TRUE.equals(verdict)) {
					AlarmEntity a = new AlarmEntity();
					a.setSkillRunId(run.getId());
					a.setTriggerEvent("skill_v2:" + sk.getSlug());
					// Tag the alarm with the machine this run checked (fan-out
					// passes tool_id per tool) so operators can tell which one.
					Object toolId = inputs.get("tool_id");
					String toolLabel = toolId != null && !String.valueOf(toolId).isBlank()
							? String.valueOf(toolId) : null;
					if (toolLabel != null) a.setEquipmentId(toolLabel);
					a.setTitle(sk.getName() + (toolLabel != null ? " · " + toolLabel : "") + " — 條件達標");
					// Describe WHY it fired (measured vs threshold) from the check
					// record, not the outcome category. Severity is authored on
					// the check block; fall back to MEDIUM.
					String headline = check == null ? null : trimToNull(check.get("headline"));
					a.setSummary(headline != null ? headline
							: sk.getOutcome() != null ? sk.getOutcome() : sk.getNl());
					a.setSeverity(normalizeSeverity(check == null ? null : check.get("severity")));
					a.setStatus("active");
					a.setEventTime(OffsetDateTime.now());
					a = alarmRepo.save(a);
					alarmId = a.getId();
					log.info("SkillV2Runner: skill={} verdict=TRUE → alarm={}", sk.getSlug(), alarmId);
				} else {
					run.setAlarmSkippedReason("verdict pass=" + verdict + " — gate 未達標，不發 alarm");
				}
			} else {
				run.setAlarmSkippedReason("role=" + sk.getRole() + " — 非 patrol（不發 alarm）");
			}
		} catch (RuntimeException ex) {
			run.setStatus("failed");
			run.setStepResults(JsonUtils.safeWrite(mapper,
					List.of(Map.of("error", String.valueOf(ex.getMessage())))));
			run.setAlarmSkippedReason("run failed: " + ex.getMessage());
			log.warn("SkillV2Runner: skill={} run failed: {}", sk.getSlug(), ex.getMessage());
		} finally {
			run.setDurationMs((int) (System.currentTimeMillis() - t0));
			run.setFinishedAt(OffsetDateTime.now());
			run = runRepo.save(run);
		}

		// Event fan-out: an alarm from a patrol fires any active v2 skill that
		// subscribes to it (trigger {kind:event, source:<this slug>}). Guard
		// against chains — an event-triggered run never re-fans-out.
		int fanned = 0;
		if (alarmId != null && !"system_event".equals(run.getTriggeredBy())) {
			fanned = fanOutToEventSubscribers(sk, alarmId);
		}

		Map<String, Object> resp = new java.util.HashMap<>();
		resp.put("ok", "failed".equals(run.getStatus()) ? Boolean.FALSE : Boolean.TRUE);
		resp.put("skill_run_id", run.getId());
		resp.put("status", run.getStatus());
		resp.put("verdict", verdict);
		if (alarmId != null) resp.put("alarm_id", alarmId);
		if (fanned > 0) resp.put("event_subscribers_fired", fanned);
		return resp;
	}

	/**
	 * Fire active v2 skills whose trigger subscribes to this skill's alarms
	 * ({kind:event, source:<upstreamSlug>}). Each runs in-process; runSystem
	 * swallows its own errors so a subscriber failure can't roll back the
	 * parent. Returns how many were fired.
	 */
	@SuppressWarnings("unchecked")
	private int fanOutToEventSubscribers(SkillV2Entity upstream, Long alarmId) {
		String upstreamSlug = upstream.getSlug();
		int fired = 0;
		for (SkillV2Entity sub : skillRepo.findByStatusOrderByNameAsc("active")) {
			if (sub.getId().equals(upstream.getId())) continue;
			Map<String, Object> cfg = JsonUtils.parseObject(mapper, sub.getTriggerConfig());
			if (!"event".equals(String.valueOf(cfg.get("kind")))) continue;
			if (!upstreamSlug.equals(String.valueOf(cfg.get("source")))) continue;
			Map<String, Object> payload = Map.of(
					"upstream_slug", upstreamSlug, "upstream_alarm_id", alarmId);
			try {
				runSystem(sub.getId(), "system_event", payload);
				fired++;
				log.info("SkillV2Runner: upstream={} alarm={} → fired event subscriber={}",
						upstreamSlug, alarmId, sub.getSlug());
			} catch (RuntimeException ex) {
				log.warn("SkillV2Runner: event subscriber {} failed: {}", sub.getSlug(), ex.getMessage());
			}
		}
		return fired;
	}

	/**
	 * Find the block_step_check verdict in an execute result. The verdict node
	 * emits a single-row "check" dataframe with a boolean `pass` field; we scan
	 * every node's preview rows for that field. Returns null if no verdict node
	 * ran (e.g. a datacheck pipeline with no step_check).
	 */
	/**
	 * Find the block_step_check output row (the whole record, not just the
	 * boolean). The verdict node emits a single-row "check" dataframe carrying
	 * {pass, value, threshold, operator, note, label, severity, headline,
	 * evidence_rows}; we scan every node's preview rows for the `pass` field and
	 * return that row so the runner can describe WHY the alarm fired. Null when
	 * no verdict node ran (e.g. a datacheck pipeline with no step_check).
	 */
	@SuppressWarnings("unchecked")
	private Map<String, Object> extractCheck(Map<String, Object> result) {
		if (result == null) return null;
		Object dataObj = result.getOrDefault("data", result);
		Map<String, Object> data = JsonUtils.asMap(dataObj);
		Object nrObj = data.get("node_results");
		if (!(nrObj instanceof Map)) return null;
		for (Object node : ((Map<String, Object>) nrObj).values()) {
			Map<String, Object> nr = JsonUtils.asMap(node);
			Object preview = nr.get("preview");
			if (!(preview instanceof Map)) continue;
			for (Object port : ((Map<String, Object>) preview).values()) {
				Map<String, Object> blob = JsonUtils.asMap(port);
				Object rows = blob.get("rows");
				if (!(rows instanceof List<?> rl) || rl.isEmpty()) continue;
				Map<String, Object> row0 = JsonUtils.asMap(rl.get(0));
				if (row0.containsKey("pass")) return row0;
			}
		}
		return null;
	}

	private static Boolean asBool(Object p) {
		if (p == null) return null;
		if (p instanceof Boolean b) return b;
		return Boolean.parseBoolean(String.valueOf(p));
	}

	private static String trimToNull(Object o) {
		if (o == null) return null;
		String s = String.valueOf(o).trim();
		return s.isEmpty() ? null : s;
	}

	/** LOW/MEDIUM/HIGH from the check record; anything else → MEDIUM. */
	private static String normalizeSeverity(Object sev) {
		String s = sev == null ? "" : String.valueOf(sev).trim().toUpperCase();
		return (s.equals("LOW") || s.equals("HIGH")) ? s : "MEDIUM";
	}

	private Map<String, Object> summarise(Map<String, Object> result, Boolean verdict, Map<String, Object> check) {
		Map<String, Object> data = JsonUtils.asMap(result.getOrDefault("data", result));
		Map<String, Object> out = new java.util.HashMap<>();
		out.put("status", result.get("status"));
		out.put("verdict", verdict);
		// Persist the check record so the alarm detail can render "為什麼達標"
		// (measured value vs threshold) without re-running the pipeline.
		if (check != null) out.put("check", check);
		Object summary = data.get("result_summary");
		if (summary != null) out.put("result_summary", summary);
		return out;
	}
}
