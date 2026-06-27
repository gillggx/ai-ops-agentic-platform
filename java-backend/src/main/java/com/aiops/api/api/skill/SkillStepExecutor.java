package com.aiops.api.api.skill;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.sidecar.PythonSidecarClient;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Executes a single skill step by dispatching its bound pipeline to the
 * sidecar's {@code /internal/pipeline/execute} endpoint and parsing the
 * response into a step-result map.
 *
 * <p>Extracted from {@code SkillRunnerService} 2026-05-23 as part of the
 * Phase 12 Java OOP refactor. The orchestrator
 * ({@link SkillRunnerService}) iterates steps and calls
 * {@link #runOneStep} for each — keeping step execution + result parsing
 * + data-view extraction out of the orchestrator's flow control.
 *
 * <p>Contract: every {@code runOneStep} call returns a normalised result map
 * with at least {@code step_id, status, value, note}. {@code status} is
 * {@code pass|fail|skipped}. Errors during pipeline dispatch are caught and
 * surfaced as {@code status="fail"} with a diagnostic note — the orchestrator
 * relies on this never throwing.
 */
@Slf4j
@Service
public class SkillStepExecutor {

	private static final TypeReference<Map<String, Object>> JSON_MAP_TYPE = new TypeReference<>() {};
	private static final Duration SIDECAR_TIMEOUT = Duration.ofSeconds(60);
	private static final int MAX_VIEW_ROWS = 20;
	private static final int MAX_VIEW_COLS = 8;

	private final PipelineRepository pipelineRepo;
	private final ObjectMapper mapper;
	private final PythonSidecarClient sidecar;

	public SkillStepExecutor(PipelineRepository pipelineRepo,
	                         ObjectMapper mapper,
	                         PythonSidecarClient sidecar) {
		this.pipelineRepo = pipelineRepo;
		this.mapper = mapper;
		this.sidecar = sidecar;
	}

	/** Run one step's bound pipeline through the sidecar.
	 *  Catches every exception so the orchestrator can always carry on to
	 *  the next step. */
	public Map<String, Object> runOneStep(String stepId,
	                                       Long pipelineId,
	                                       Map<String, Object> payload,
	                                       AuthPrincipal caller) {
		return runOneStep(stepId, pipelineId, payload, caller, null, null);
	}

	/**
	 * 2026-06-26: overload that forwards skill_id + triggered_by + payload
	 * snapshot to the sidecar so the row written into execution_logs reflects
	 * the calling skill / scheduler path (no more skill_id=-1 + triggered_by=
	 * 'user' on every system-event dispatch). Older callers can keep using the
	 * 4-arg form and get the legacy behaviour.
	 */
	public Map<String, Object> runOneStep(String stepId,
	                                       Long pipelineId,
	                                       Map<String, Object> payload,
	                                       AuthPrincipal caller,
	                                       Long skillId,
	                                       String triggeredBy) {
		long t0 = System.currentTimeMillis();
		try {
			PipelineEntity pe = pipelineRepo.findById(pipelineId).orElse(null);
			if (pe == null) {
				return stepResultError(stepId, "pipeline not found: " + pipelineId);
			}
			String pipelineJson = pe.getPipelineJson();
			if (pipelineJson == null || pipelineJson.isBlank()) {
				return stepResultError(stepId, "pipeline_json empty");
			}
			Map<String, Object> body = new HashMap<>();
			// Sidecar /internal/pipeline/execute expects a parsed JSON, not a string.
			body.put("pipeline_json", mapper.readValue(pipelineJson, JSON_MAP_TYPE));
			body.put("inputs", payload != null ? payload : Map.of());
			if (triggeredBy != null && !triggeredBy.isBlank()) {
				body.put("triggered_by", triggeredBy);
			}
			if (skillId != null) {
				body.put("skill_id", skillId);
			}
			// event_context: serialise the trigger payload + minimal routing
			// hint so post-mortem can see which step + which skill caused
			// this execution row. Trim long values to keep the column manageable.
			body.put("event_context", buildEventContext(skillId, stepId, payload));

			@SuppressWarnings("rawtypes")
			Map result = sidecar.postJson("/internal/pipeline/execute", body, Map.class, caller)
					.block(SIDECAR_TIMEOUT);
			return parseRunResult(stepId, result, System.currentTimeMillis() - t0);
		} catch (RuntimeException | JsonProcessingException ex) {
			// JsonProcessingException for mapper.readValue(pipelineJson) above;
			// RuntimeException for reactor block() (timeout / WebClient error).
			// Both surface as step fail with diagnostic note — orchestrator
			// keeps going to the next step.
			log.warn("step {} pipeline {} crashed: {}", stepId, pipelineId, ex.toString());
			return stepResultError(stepId, ex.getClass().getSimpleName() + ": " + ex.getMessage());
		}
	}

	private String buildEventContext(Long skillId, String stepId, Map<String, Object> payload) {
		Map<String, Object> ctx = new HashMap<>();
		ctx.put("skill_id", skillId);
		ctx.put("step_id", stepId);
		ctx.put("payload", payload != null ? payload : Map.of());
		try {
			return mapper.writeValueAsString(ctx);
		} catch (JsonProcessingException e) {
			return "{}";
		}
	}

	public Map<String, Object> stepResultError(String stepId, String msg) {
		Map<String, Object> sr = new HashMap<>();
		sr.put("step_id", stepId);
		sr.put("status", "fail");
		sr.put("value", "error");
		sr.put("note", msg);
		return sr;
	}

	public Map<String, Object> stepResultPending(String stepId, String reason) {
		Map<String, Object> sr = new HashMap<>();
		sr.put("step_id", stepId);
		sr.put("status", "skipped");
		sr.put("value", "—");
		sr.put("note", reason);
		return sr;
	}

	// ── Result parsing ──────────────────────────────────────────────────────

	@SuppressWarnings({"unchecked", "rawtypes"})
	private Map<String, Object> parseRunResult(String stepId, Map result, long elapsedMs) {
		if (result == null) return stepResultError(stepId, "sidecar returned null");
		String overall = String.valueOf(result.get("status"));
		if (!"success".equals(overall)) {
			return stepResultError(stepId, "pipeline " + overall + ": " + result.get("error_message"));
		}
		Object nrObj = result.get("node_results");
		Map<String, Object> nodeResults = nrObj instanceof Map<?, ?>
				? (Map<String, Object>) nrObj : Map.of();
		// Find the block_step_check output. Convention: last node's output port "check".
		// Phase 11 v6 — sidecar's pipeline_executor wraps block return values
		// in "preview" (with shape {type: "dataframe", columns, rows, total}),
		// not "outputs". Check both for forward-compat.
		Map<String, Object> stepCheck = null;
		for (Map.Entry<String, Object> e : nodeResults.entrySet()) {
			Map<String, Object> nr = (Map<String, Object>) e.getValue();
			for (String key : new String[]{"outputs", "preview"}) {
				Object portsObj = nr.get(key);
				if (!(portsObj instanceof Map<?, ?> ports)) continue;
				if (ports.containsKey("check")) {
					stepCheck = (Map<String, Object>) ports.get("check");
					break;
				}
			}
		}
		Map<String, Object> sr = new HashMap<>();
		sr.put("step_id", stepId);
		sr.put("duration_ms", elapsedMs);
		// Phase 11 v10 — pass through sidecar's per-node dataframe previews so
		// the report can show what data the pipeline actually fetched (not
		// just the boolean check verdict). User feedback: 「我要看 pipeline
		// 的資料本身，不只是 yes/no」. v11 — read result_summary.data_views
		// (block_data_view nodes) so it matches Pipeline-Builder try-run.
		sr.put("data_views", extractDataViews((Map<String, Object>) result, nodeResults));
		// Forward the FULL pipeline result_summary (charts + data_views) so the
		// skill try-run renders each step with the SAME ResultsBody component as a
		// single-pipeline run / pipeline-view — not a tables-only side path. A
		// step's chart (e.g. a by-hour OOC bar) was computed but previously dropped.
		sr.put("result_summary", result.get("result_summary"));
		if (stepCheck == null) {
			// Pipeline ran but no step_check output — treat as fail with diagnostic note
			sr.put("status", "fail");
			sr.put("value", "no step_check output");
			sr.put("note", "skill-step pipelines must end in block_step_check");
			return sr;
		}
		// step_check emits a single-row dataframe — extract first row.
		List<Map<String, Object>> rows = (List<Map<String, Object>>) stepCheck.getOrDefault("rows", List.of());
		Map<String, Object> row = rows.isEmpty() ? Map.of() : rows.get(0);
		boolean pass = Boolean.TRUE.equals(row.get("pass"));
		sr.put("status", pass ? "pass" : "fail");
		sr.put("value", String.valueOf(row.getOrDefault("value", "")));
		sr.put("note", String.valueOf(row.getOrDefault("note", "")));
		sr.put("threshold", row.get("threshold"));
		sr.put("operator", row.get("operator"));
		return sr;
	}

	/** Phase 11 v11 — align Skill report's data views with Pipeline-Builder's
	 *  try-run panel: both should show the **curated** views the pipeline
	 *  author marked with {@code block_data_view} nodes, NOT every intermediate
	 *  dataframe. Sidecar already does this work in
	 *  {@code _collect_data_view_summaries} → exposed at
	 *  {@code result.result_summary.data_views}. We just pass it through.
	 *  Caps cols/rows to keep SSE payload bounded. */
	@SuppressWarnings({"unchecked", "rawtypes"})
	private List<Map<String, Object>> extractDataViews(Map<String, Object> result, Map<String, Object> nodeResults) {
		Object rsObj = result.get("result_summary");
		if (rsObj instanceof Map<?, ?> rs) {
			Object dvsObj = ((Map<String, Object>) rs).get("data_views");
			if (dvsObj instanceof List<?> dvs && !dvs.isEmpty()) {
				List<Map<String, Object>> views = new ArrayList<>();
				for (Object dvObj : dvs) {
					if (!(dvObj instanceof Map<?, ?> dv)) continue;
					Object cols = ((Map<String, Object>) dv).get("columns");
					Object rows = ((Map<String, Object>) dv).get("rows");
					Object total = ((Map<String, Object>) dv).get("total_rows");
					Map<String, Object> view = new HashMap<>();
					view.put("node_id", String.valueOf(((Map<String, Object>) dv).getOrDefault("node_id", "")));
					view.put("block", String.valueOf(((Map<String, Object>) dv).getOrDefault("title", "")));
					view.put("port", String.valueOf(((Map<String, Object>) dv).getOrDefault("description", "")));
					if (cols instanceof List<?> cl) {
						view.put("columns", ((List<Object>) cl).subList(0, Math.min(cl.size(), MAX_VIEW_COLS)));
					} else {
						view.put("columns", List.of());
					}
					if (rows instanceof List<?> rl) {
						view.put("rows", ((List<Object>) rl).subList(0, Math.min(rl.size(), MAX_VIEW_ROWS)));
					} else {
						view.put("rows", List.of());
					}
					view.put("total", total instanceof Number n ? n.intValue() : (rows instanceof List<?> rl2 ? rl2.size() : 0));
					views.add(view);
				}
				return views;
			}
		}
		// Fallback for legacy pipelines that don't declare block_data_view:
		// surface terminal-node dataframes only (skip "check" — already shown
		// as the verdict), capped to 1 view to keep payload tiny.
		Object terminalsObj = result.get("terminal_nodes");
		Set<String> terminals = new HashSet<>();
		if (terminalsObj instanceof List<?> tl) {
			for (Object t : tl) terminals.add(String.valueOf(t));
		}
		for (Map.Entry<String, Object> e : nodeResults.entrySet()) {
			if (!terminals.isEmpty() && !terminals.contains(e.getKey())) continue;
			if (!(e.getValue() instanceof Map<?, ?> nr)) continue;
			String blockName = String.valueOf(((Map<String, Object>) nr).getOrDefault("block", ""));
			for (String key : new String[]{"outputs", "preview"}) {
				Object portsObj = ((Map<String, Object>) nr).get(key);
				if (!(portsObj instanceof Map<?, ?> ports)) continue;
				for (Map.Entry<?, ?> pe : ports.entrySet()) {
					String port = String.valueOf(pe.getKey());
					if ("check".equals(port)) continue;
					if (!(pe.getValue() instanceof Map<?, ?> portVal)) continue;
					if (!"dataframe".equals(String.valueOf(((Map<String, Object>) portVal).get("type")))) continue;
					Object colsObj = ((Map<String, Object>) portVal).get("columns");
					Object rowsObj = ((Map<String, Object>) portVal).get("rows");
					Object totalObj = ((Map<String, Object>) portVal).get("total");
					if (!(colsObj instanceof List<?>)) continue;
					List<Object> cols = (List<Object>) colsObj;
					List<Object> rows = rowsObj instanceof List<?> ? (List<Object>) rowsObj : List.of();
					Map<String, Object> view = new HashMap<>();
					view.put("node_id", e.getKey());
					view.put("block", blockName);
					view.put("port", port);
					view.put("columns", cols.subList(0, Math.min(cols.size(), MAX_VIEW_COLS)));
					view.put("rows", rows.subList(0, Math.min(rows.size(), MAX_VIEW_ROWS)));
					view.put("total", totalObj instanceof Number n ? n.intValue() : rows.size());
					return List.of(view);   // only one fallback view
				}
			}
		}
		return List.of();
	}
}
