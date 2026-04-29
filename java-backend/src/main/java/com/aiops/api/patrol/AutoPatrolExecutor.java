package com.aiops.api.patrol;

import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.domain.patrol.AutoPatrolEntity;
import com.aiops.api.domain.patrol.AutoPatrolRepository;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.pipeline.PipelineRunEntity;
import com.aiops.api.domain.pipeline.PipelineRunRepository;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Runs one Auto-Patrol fire: load patrol → expand scope → for each target →
 * resolve input_binding → call sidecar pipeline executor → if triggered,
 * write Alarm row.
 *
 * <p>Phase 5-minimal: no execution-history rows ({@code pb_pipeline_runs}),
 * no audit log, no retry / dead-letter. Errors are logged + the run is
 * skipped so subsequent patrol fires aren't affected.
 */
@Slf4j
@Component
public class AutoPatrolExecutor {

	private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};
	private static final int DEFAULT_FANOUT_CAP = 20;

	private final AutoPatrolRepository patrolRepo;
	private final PipelineRepository pipelineRepo;
	private final PipelineRunRepository pipelineRunRepo;
	private final AlarmRepository alarmRepo;
	private final SimulatorClient simulatorClient;
	private final ObjectMapper objectMapper;
	private final WebClient sidecarWebClient;
	private final String sidecarServiceToken;

	public AutoPatrolExecutor(AutoPatrolRepository patrolRepo,
	                          PipelineRepository pipelineRepo,
	                          PipelineRunRepository pipelineRunRepo,
	                          AlarmRepository alarmRepo,
	                          SimulatorClient simulatorClient,
	                          ObjectMapper objectMapper,
	                          @Value("${aiops.sidecar.python.base-url}") String sidecarBaseUrl,
	                          @Value("${aiops.sidecar.python.service-token}") String sidecarServiceToken) {
		this.patrolRepo = patrolRepo;
		this.pipelineRepo = pipelineRepo;
		this.pipelineRunRepo = pipelineRunRepo;
		this.alarmRepo = alarmRepo;
		this.simulatorClient = simulatorClient;
		this.objectMapper = objectMapper;
		this.sidecarServiceToken = sidecarServiceToken;
		this.sidecarWebClient = WebClient.builder().baseUrl(sidecarBaseUrl).build();
	}

	/** Returned by {@link #executePatrol} so callers (manual /trigger
	 *  endpoint, scheduler thread) can summarise what happened without
	 *  re-querying pb_pipeline_runs. {@code runId} points at the row
	 *  that was just written so the UI can deep-link to it. */
	public record PatrolRunResult(
			Long runId,
			Long patrolId,
			Long pipelineId,
			int fanoutCount,
			int triggeredCount,
			String status,
			String errorMessage) {

		static PatrolRunResult failed(Long patrolId, Long pipelineId,
		                              int fanoutCount, int triggeredCount, String error) {
			return new PatrolRunResult(null, patrolId, pipelineId,
					fanoutCount, triggeredCount, "failed", error);
		}
	}

	/** Write the pipeline_runs row + return a summary mirror to the caller. */
	private PatrolRunResult persistRunAndReturn(Long patrolId, Long pipelineId,
	                                             String pipelineVersion, String triggeredBy,
	                                             int fanoutCount, int triggeredCount,
	                                             String status, String errorMessage,
	                                             List<Map<String, Object>> targetSummaries) {
		PipelineRunEntity run = new PipelineRunEntity();
		run.setPipelineId(pipelineId);
		run.setPipelineVersion(pipelineVersion != null ? pipelineVersion : "1.0.0");
		run.setTriggeredBy(triggeredBy);
		run.setStatus(status);
		run.setFinishedAt(OffsetDateTime.now());
		if (errorMessage != null) run.setErrorMessage(truncate(errorMessage, 4000));
		Map<String, Object> nodeResults = new HashMap<>();
		nodeResults.put("patrol_id", patrolId);
		nodeResults.put("fanout_count", fanoutCount);
		nodeResults.put("triggered_count", triggeredCount);
		nodeResults.put("targets", targetSummaries);
		try {
			run.setNodeResults(objectMapper.writeValueAsString(nodeResults));
		} catch (Exception ex) {
			run.setNodeResults("{\"error\":\"failed to serialize node_results\"}");
		}
		try {
			run = pipelineRunRepo.save(run);
		} catch (Exception ex) {
			log.warn("Failed to write pb_pipeline_runs row for patrol {}: {}",
					patrolId, ex.getMessage());
		}
		return new PatrolRunResult(run.getId(), patrolId, pipelineId,
				fanoutCount, triggeredCount, status, errorMessage);
	}

	private static String truncate(String s, int max) {
		if (s == null || s.length() <= max) return s;
		return s.substring(0, max);
	}

	/** Cron tick / once-fire / manual /trigger entry point.
	 *
	 *  <p>Always writes a {@code pb_pipeline_runs} row (one per fire, not per
	 *  target) summarising what happened. Returns the same summary so the
	 *  manual /trigger endpoint can hand it to the UI directly. Skips that
	 *  produce no work (pipeline missing, archived, scope empty) still write
	 *  a row so the user can see "this patrol fired but had nothing to do". */
	@Transactional
	public PatrolRunResult executePatrol(Long patrolId) {
		String triggeredBy = "auto_patrol";
		AutoPatrolEntity patrol = patrolRepo.findById(patrolId).orElse(null);
		if (patrol == null) {
			log.warn("executePatrol: patrol id={} not found (was it deleted?)", patrolId);
			return PatrolRunResult.failed(patrolId, null, 0, 0, "patrol not found");
		}
		Long pipelineId = patrol.getPipelineId();
		if (pipelineId == null) {
			log.warn("executePatrol: patrol id={} has no pipeline_id; skip", patrolId);
			return persistRunAndReturn(patrolId, null, "1.0.0", triggeredBy, 0, 0,
					"failed", "patrol has no pipeline_id", List.of());
		}
		PipelineEntity pipeline = pipelineRepo.findById(pipelineId).orElse(null);
		if (pipeline == null) {
			log.warn("executePatrol: patrol id={} → pipeline id={} not found; skip", patrolId, pipelineId);
			return persistRunAndReturn(patrolId, pipelineId, "1.0.0", triggeredBy, 0, 0,
					"failed", "pipeline not found", List.of());
		}
		String pipelineVersion = pipeline.getVersion() != null ? pipeline.getVersion() : "1.0.0";
		// Pipeline must be in a runnable state; archived = no-op (still
		// recorded so user can see the skip + reason).
		if ("archived".equals(pipeline.getStatus())) {
			log.info("executePatrol: patrol id={} → pipeline id={} archived; skip", patrolId, pipelineId);
			return persistRunAndReturn(patrolId, pipelineId, pipelineVersion, triggeredBy, 0, 0,
					"skipped", "pipeline is archived", List.of());
		}

		List<Map<String, Object>> targets;
		try {
			targets = expandScope(patrol);
		} catch (Exception ex) {
			log.warn("executePatrol: patrol id={} scope expansion failed: {}", patrolId, ex.getMessage());
			return persistRunAndReturn(patrolId, pipelineId, pipelineVersion, triggeredBy, 0, 0,
					"failed", "scope expansion failed: " + ex.getMessage(), List.of());
		}
		if (targets.isEmpty()) {
			log.info("executePatrol: patrol id={} scope expanded to 0 targets", patrolId);
			return persistRunAndReturn(patrolId, pipelineId, pipelineVersion, triggeredBy, 0, 0,
					"success", null, List.of());
		}

		Map<String, Object> bindingTemplate = parseBinding(patrol.getInputBinding());

		log.info("executePatrol: patrol id={} firing — pipeline={} fanout={} mode={}",
				patrolId, pipelineId, targets.size(), patrol.getTriggerMode());

		int triggeredCount = 0;
		List<Map<String, Object>> targetSummaries = new ArrayList<>();
		for (Map<String, Object> target : targets) {
			Map<String, Object> inputs = resolveBinding(bindingTemplate, target);
			Map<String, Object> result = callSidecar(pipelineId, inputs);
			Map<String, Object> tSum = new HashMap<>();
			tSum.put("tool_id", target.get("tool_id"));
			if (target.get("step") != null) tSum.put("step", target.get("step"));
			if (result == null) {
				tSum.put("status", "sidecar_error");
				tSum.put("triggered", false);
			} else {
				boolean triggered = isTriggered(result);
				tSum.put("status", "ok");
				tSum.put("triggered", triggered);
				if (triggered) {
					writeAlarm(patrol, target, result);
					triggeredCount++;
				}
			}
			targetSummaries.add(tSum);
		}
		log.info("executePatrol: patrol id={} done — {}/{} targets triggered",
				patrolId, triggeredCount, targets.size());
		return persistRunAndReturn(patrolId, pipelineId, pipelineVersion, triggeredBy,
				targets.size(), triggeredCount, "success", null, targetSummaries);
	}

	// ── Scope expansion ───────────────────────────────────────────────────

	@SuppressWarnings("unchecked")
	List<Map<String, Object>> expandScope(AutoPatrolEntity patrol) {
		Map<String, Object> scope = parseScope(patrol.getTargetScope());
		String type = String.valueOf(scope.getOrDefault("type", "event_driven"));
		int cap = ((Number) scope.getOrDefault("fanout_cap", DEFAULT_FANOUT_CAP)).intValue();

		switch (type) {
			case "event_driven" -> {
				// schedule/once shouldn't reach here — but if a patrol was
				// configured as event but firing via cron somehow, skip.
				log.warn("patrol id={} scope=event_driven but reached executor; skip", patrol.getId());
				return List.of();
			}
			case "all_equipment" -> {
				List<Map<String, Object>> all = simulatorClient.listAllTools();
				return takeUpTo(all, cap);
			}
			case "specific_equipment" -> {
				Object idsRaw = scope.get("equipment_ids");
				if (!(idsRaw instanceof List<?> idsList)) return List.of();
				List<Map<String, Object>> out = new ArrayList<>();
				for (Object o : idsList) {
					if (o == null) continue;
					Map<String, Object> t = new HashMap<>();
					t.put("tool_id", String.valueOf(o));
					out.add(t);
				}
				return takeUpTo(out, cap);
			}
			case "by_step" -> {
				String step = String.valueOf(scope.getOrDefault("step", ""));
				if (step.isBlank()) return List.of();
				List<Map<String, Object>> all = simulatorClient.listAllTools();
				List<Map<String, Object>> filtered = all.stream()
						.filter(t -> step.equals(String.valueOf(t.get("step"))))
						.toList();
				List<Map<String, Object>> out = new ArrayList<>();
				for (Map<String, Object> t : filtered) {
					Map<String, Object> entry = new HashMap<>(t);
					entry.put("step", step);  // ensure step is in the binding map
					out.add(entry);
				}
				return takeUpTo(out, cap);
			}
			default -> {
				log.warn("patrol id={} unknown scope type='{}'; skip", patrol.getId(), type);
				return List.of();
			}
		}
	}

	private static <T> List<T> takeUpTo(List<T> src, int cap) {
		if (src.size() <= cap) return src;
		return src.subList(0, cap);
	}

	// ── Input binding ─────────────────────────────────────────────────────

	/** Resolve "$loop.X" tokens in the binding template against a target map.
	 *  Literal values pass through unchanged. */
	Map<String, Object> resolveBinding(Map<String, Object> template, Map<String, Object> target) {
		Map<String, Object> out = new HashMap<>();
		for (Map.Entry<String, Object> e : template.entrySet()) {
			Object v = e.getValue();
			if (v instanceof String s && s.startsWith("$loop.")) {
				String key = s.substring("$loop.".length());
				out.put(e.getKey(), target.get(key));
			} else {
				out.put(e.getKey(), v);
			}
		}
		// Convenience: if template is empty and target has tool_id, expose it
		// so the pipeline can still bind by name.
		if (out.isEmpty() && target.get("tool_id") != null) {
			out.put("tool_id", target.get("tool_id"));
		}
		return out;
	}

	// ── Sidecar call ──────────────────────────────────────────────────────

	@SuppressWarnings("unchecked")
	Map<String, Object> callSidecar(Long pipelineId, Map<String, Object> inputs) {
		Map<String, Object> body = new HashMap<>();
		body.put("pipeline_id", pipelineId);
		body.put("inputs", inputs);
		body.put("triggered_by", "auto_patrol");
		try {
			Map<String, Object> resp = sidecarWebClient.post()
					.uri("/internal/pipeline/execute")
					.header("X-Service-Token", sidecarServiceToken)
					.bodyValue(body)
					.retrieve()
					.bodyToMono(Map.class)
					.timeout(Duration.ofSeconds(60))
					.onErrorResume(ex -> {
						log.warn("sidecar execute failed for pipeline {}: {}", pipelineId, ex.getMessage());
						return Mono.empty();
					})
					.block();
			return resp;
		} catch (Exception ex) {
			log.warn("sidecar execute threw for pipeline {}: {}", pipelineId, ex.getMessage());
			return null;
		}
	}

	@SuppressWarnings("unchecked")
	private boolean isTriggered(Map<String, Object> result) {
		Object summary = result.get("result_summary");
		if (summary instanceof Map<?, ?> m) {
			Object triggered = ((Map<String, Object>) m).get("triggered");
			return Boolean.TRUE.equals(triggered);
		}
		return false;
	}

	// ── Alarm write ───────────────────────────────────────────────────────

	private void writeAlarm(AutoPatrolEntity patrol, Map<String, Object> target,
	                        Map<String, Object> result) {
		AlarmEntity alarm = new AlarmEntity();
		alarm.setSkillId(null);  // pipeline-based; no SkillDefinition row
		alarm.setTriggerEvent("auto_patrol:" + patrol.getId());
		String toolId = String.valueOf(target.getOrDefault("tool_id", ""));
		alarm.setEquipmentId(toolId);
		alarm.setLotId("");
		Object stepRaw = target.get("step");
		if (stepRaw != null) alarm.setStep(String.valueOf(stepRaw));
		alarm.setEventTime(OffsetDateTime.now());
		alarm.setSeverity(patrol.getAlarmSeverity() != null ? patrol.getAlarmSeverity() : "MEDIUM");
		String title = patrol.getAlarmTitle();
		if (title == null || title.isBlank()) title = "[Auto-Patrol] " + patrol.getName();
		// Compose summary as compact JSON of result_summary + tool context
		Map<String, Object> summary = new HashMap<>();
		summary.put("tool_id", toolId);
		summary.put("patrol_id", patrol.getId());
		summary.put("pipeline_id", patrol.getPipelineId());
		summary.put("result_summary", result.get("result_summary"));
		try {
			alarm.setSummary(objectMapper.writeValueAsString(summary));
		} catch (Exception ex) {
			alarm.setSummary("{\"error\":\"failed to serialize summary\"}");
		}
		alarm.setTitle(title.length() > 300 ? title.substring(0, 300) : title);
		alarm.setStatus("active");
		alarmRepo.save(alarm);
		log.info("alarm written: patrol={} tool={} title='{}'", patrol.getId(), toolId, title);
	}

	// ── Helpers ───────────────────────────────────────────────────────────

	private Map<String, Object> parseScope(String json) {
		if (json == null || json.isBlank()) return Map.of("type", "event_driven");
		try {
			return objectMapper.readValue(json, MAP_TYPE);
		} catch (Exception ex) {
			log.warn("target_scope parse failed ('{}'): {}", json, ex.getMessage());
			return Map.of("type", "event_driven");
		}
	}

	private Map<String, Object> parseBinding(String json) {
		if (json == null || json.isBlank()) return Map.of();
		try {
			return objectMapper.readValue(json, MAP_TYPE);
		} catch (Exception ex) {
			log.warn("input_binding parse failed ('{}'): {}", json, ex.getMessage());
			return Map.of();
		}
	}
}
