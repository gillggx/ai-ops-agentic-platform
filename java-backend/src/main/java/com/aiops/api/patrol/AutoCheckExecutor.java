package com.aiops.api.patrol;

import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
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
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Phase C — runs an auto_check pipeline in response to an alarm.
 *
 * <p>Unlike {@link AutoPatrolExecutor}, an auto_check has no patrol entity —
 * the binding lives in {@code pipeline_auto_check_triggers} as a
 * (pipeline_id, event_type) row. When an alarm with matching trigger_event
 * lands, EventDispatchService calls
 * {@link #executeAutoCheck(Long, Map, Long)} per matched pipeline.
 *
 * <p>Critically: this executor does NOT write a new alarm even if the
 * pipeline triggers. Otherwise we'd loop alarm → check → alarm → check.
 * The pipeline run is recorded in {@code pb_pipeline_runs} (triggered_by
 * = "auto_check") — that is the user-visible audit trail.
 */
@Slf4j
@Component
public class AutoCheckExecutor {

	private final PipelineRepository pipelineRepo;
	private final PipelineRunRepository pipelineRunRepo;
	private final AlarmRepository alarmRepo;
	private final ObjectMapper objectMapper;
	private final WebClient sidecarWebClient;
	private final String sidecarServiceToken;

	public AutoCheckExecutor(PipelineRepository pipelineRepo,
	                         PipelineRunRepository pipelineRunRepo,
	                         AlarmRepository alarmRepo,
	                         ObjectMapper objectMapper,
	                         @Value("${aiops.sidecar.python.base-url}") String sidecarBaseUrl,
	                         @Value("${aiops.sidecar.python.service-token}") String sidecarServiceToken) {
		this.pipelineRepo = pipelineRepo;
		this.pipelineRunRepo = pipelineRunRepo;
		this.alarmRepo = alarmRepo;
		this.objectMapper = objectMapper;
		this.sidecarServiceToken = sidecarServiceToken;
		// 16 MiB buffer — pipeline results with data_view rows / full process_history
		// dumps routinely exceed Spring WebClient's default 256 KiB ceiling and
		// would otherwise abort response parsing with DataBufferLimitException.
		this.sidecarWebClient = WebClient.builder()
				.baseUrl(sidecarBaseUrl)
				.codecs(c -> c.defaultCodecs().maxInMemorySize(16 * 1024 * 1024))
				.build();
	}

	/** Run an auto_check pipeline. Always writes a pb_pipeline_runs row.
	 *
	 *  @param pipelineId    the diagnostic pipeline to run
	 *  @param alarmPayload  fields from the alarm (equipment_id, lot_id,
	 *                       step, severity, summary, …) — passed to the
	 *                       sidecar as the pipeline {@code inputs} map after
	 *                       a tool_id ↔ equipment_id mirror.
	 *  @param sourceAlarmId for traceability in the run row's node_results.
	 */
	@Transactional
	public void executeAutoCheck(Long pipelineId, Map<String, Object> alarmPayload, Long sourceAlarmId) {
		PipelineEntity pipeline = pipelineRepo.findById(pipelineId).orElse(null);
		if (pipeline == null) {
			log.warn("auto_check: pipeline id={} not found; skip", pipelineId);
			return;
		}
		if ("archived".equals(pipeline.getStatus())) {
			log.info("auto_check: pipeline id={} archived; skip", pipelineId);
			return;
		}
		// Safety net: validator rejects auto_check pipelines containing
		// block_alert at publish time, but legacy data published before that
		// rule may still be lurking. Refuse to fire those — emitting an alarm
		// from auto_check would re-enter EventDispatchService.dispatchAlarm
		// and loop indefinitely.
		if (pipelineHasBlockAlert(pipeline)) {
			log.warn("auto_check: pipeline id={} contains block_alert (only auto_patrol may emit alarms); refusing to fire — republish without block_alert",
					pipelineId);
			return;
		}

		// Mirror equipment_id ↔ tool_id same as patrol event mode so the
		// pipeline can declare either name on its inputs.
		Map<String, Object> inputs = new HashMap<>(alarmPayload != null ? alarmPayload : Map.of());
		if (inputs.get("tool_id") == null && inputs.get("equipment_id") != null) {
			inputs.put("tool_id", inputs.get("equipment_id"));
		} else if (inputs.get("equipment_id") == null && inputs.get("tool_id") != null) {
			inputs.put("equipment_id", inputs.get("tool_id"));
		}

		log.info("auto_check: firing pipeline={} from alarm={}", pipelineId, sourceAlarmId);
		Map<String, Object> result = callSidecar(pipelineId, inputs);
		boolean triggered = result != null && isTriggered(result);
		String status = result == null ? "failed" : "success";
		String error = result == null ? "sidecar execute failed" : null;

		Map<String, Object> nodeResults = new LinkedHashMap<>();
		nodeResults.put("source_alarm_id", sourceAlarmId);
		nodeResults.put("triggered", triggered);
		nodeResults.put("inputs_echo", abbreviate(inputs));
		if (result != null) nodeResults.put("result_summary", result.get("result_summary"));

		PipelineRunEntity run = new PipelineRunEntity();
		run.setPipelineId(pipelineId);
		run.setPipelineVersion(pipeline.getVersion() != null ? pipeline.getVersion() : "1.0.0");
		run.setTriggeredBy("auto_check");
		run.setStatus(status);
		run.setFinishedAt(OffsetDateTime.now());
		if (error != null) run.setErrorMessage(error);
		try {
			run.setNodeResults(objectMapper.writeValueAsString(nodeResults));
		} catch (Exception ex) {
			run.setNodeResults("{\"error\":\"failed to serialize node_results\"}");
		}
		PipelineRunEntity savedRun = null;
		try {
			savedRun = pipelineRunRepo.save(run);
		} catch (Exception ex) {
			log.warn("auto_check: failed to persist run row for pipeline={}: {}",
					pipelineId, ex.getMessage());
		}

		// Wire the diagnostic run id back onto the source alarm so the alarm
		// detail UI / API can deep-link to "what auto_check found out". Without
		// this, alarm.diagnostic_log_id stays NULL and the user sees no
		// connection between the alarm and the diagnostic pipeline output.
		if (savedRun != null && sourceAlarmId != null) {
			final Long runId = savedRun.getId() != null ? savedRun.getId().longValue() : null;
			if (runId != null) {
				try {
					alarmRepo.findById(sourceAlarmId).ifPresent(a -> {
						a.setDiagnosticLogId(runId);
						alarmRepo.save(a);
					});
				} catch (Exception ex) {
					log.warn("auto_check: failed to backlink diagnostic_log_id on alarm={}: {}",
							sourceAlarmId, ex.getMessage());
				}
			}
		}
	}

	@SuppressWarnings("unchecked")
	private Map<String, Object> callSidecar(Long pipelineId, Map<String, Object> inputs) {
		Map<String, Object> body = new HashMap<>();
		body.put("pipeline_id", pipelineId);
		body.put("inputs", inputs);
		body.put("triggered_by", "auto_check");
		try {
			return sidecarWebClient.post()
					.uri("/internal/pipeline/execute")
					.header("X-Service-Token", sidecarServiceToken)
					.bodyValue(body)
					.retrieve()
					.bodyToMono(Map.class)
					.timeout(Duration.ofSeconds(60))
					.onErrorResume(ex -> {
						log.warn("auto_check: sidecar execute failed for pipeline {}: {}",
								pipelineId, ex.getMessage());
						return Mono.empty();
					})
					.block();
		} catch (Exception ex) {
			log.warn("auto_check: sidecar execute threw for pipeline {}: {}",
					pipelineId, ex.getMessage());
			return null;
		}
	}

	@SuppressWarnings("unchecked")
	private boolean isTriggered(Map<String, Object> result) {
		Object summary = result.get("result_summary");
		if (summary instanceof Map<?, ?> m) {
			return Boolean.TRUE.equals(((Map<String, Object>) m).get("triggered"));
		}
		return false;
	}

	/** Truncate string values in inputs for the run row's node_results echo
	 *  so we don't bloat pb_pipeline_runs with multi-KB blobs. */
	private static Map<String, Object> abbreviate(Map<String, Object> in) {
		Map<String, Object> out = new LinkedHashMap<>();
		for (Map.Entry<String, Object> e : in.entrySet()) {
			Object v = e.getValue();
			if (v instanceof String s && s.length() > 100) {
				out.put(e.getKey(), s.substring(0, 100) + "…");
			} else {
				out.put(e.getKey(), v);
			}
		}
		return out;
	}

	/** Static type token shared by sidecar response + pipeline_json parsing. */
	private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

	/** Parse pipeline_json and look for any block_alert node. Best-effort —
	 *  malformed JSON or missing nodes returns false (the executor will then
	 *  attempt the run and any sidecar issue surfaces in the run row). */
	@SuppressWarnings("unchecked")
	private boolean pipelineHasBlockAlert(PipelineEntity pipeline) {
		String raw = pipeline.getPipelineJson();
		if (raw == null || raw.isBlank()) return false;
		try {
			Map<String, Object> json = objectMapper.readValue(raw, MAP_TYPE);
			Object nodes = json.get("nodes");
			if (!(nodes instanceof java.util.List<?> list)) return false;
			for (Object n : list) {
				if (n instanceof Map<?, ?> m
						&& "block_alert".equals(((Map<String, Object>) m).get("block_id"))) {
					return true;
				}
			}
			return false;
		} catch (Exception ex) {
			log.debug("pipelineHasBlockAlert: parse failed for pipeline {}: {}",
					pipeline.getId(), ex.getMessage());
			return false;
		}
	}
}
