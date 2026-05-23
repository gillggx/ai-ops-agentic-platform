package com.aiops.api.api.skill;

import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.domain.skill.ExecutionLogEntity;
import com.aiops.api.domain.skill.ExecutionLogRepository;
import com.aiops.api.domain.skill.SkillDocumentEntity;
import com.aiops.api.domain.skill.SkillRunEntity;
import com.aiops.api.scheduler.SchedulerHttpClient;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Alarm emission for skill runs.
 *
 * <p>Extracted from {@code SkillRunnerService} 2026-05-23 as part of the
 * Phase 12 Java OOP refactor. SkillRunnerService stays focused on
 * orchestration (iterating steps + emitting SSE events); writing an alarm
 * row after a triggered patrol — and the cascade to ExecutionLog +
 * SchedulerHttpClient.dispatchAlarm — lives here.
 *
 * <p>Guard rules and dedup window preserved verbatim from the original
 * SkillRunnerService v30.13. Counters survive the split intact — the
 * orchestrator's {@code alarmEmitStats()} delegates here so the
 * SystemMonitorAliasController consumer doesn't change.
 *
 * <p>Method visibility is package-private on the emission/helper surface so
 * {@code SkillAlarmEmitterTest} (formerly SkillRunnerServiceTest) can keep
 * unit-testing every guard branch without going through reflection.
 */
@Slf4j
@Service
public class SkillAlarmEmitter {

	private static final TypeReference<Map<String, Object>> JSON_MAP_TYPE = new TypeReference<>() {};
	private static final Duration ALARM_DEDUP_WINDOW = Duration.ofHours(1);
	private static final String ALARM_TRIGGER_EVENT_PATROL = "patrol_check";

	private final AlarmRepository alarmRepo;
	private final ExecutionLogRepository execLogRepo;
	private final SchedulerHttpClient scheduler;
	private final ObjectMapper mapper;

	/** v30.13b (2026-05-17) — in-memory counters surfaced via System Monitor.
	 *  Reset on JVM restart (acceptable — service runs as long-lived systemd
	 *  unit; restart cadence is human-driven). For persistent metrics, query
	 *  alarms / skill_runs tables directly. */
	private final AtomicLong alarmsEmitted = new AtomicLong(0);
	private final AtomicLong alarmsDedupSuppressed = new AtomicLong(0);
	private volatile String lastEmitAtIso = null;
	private volatile String lastEmitSkillSlug = null;
	private volatile Long lastEmitAlarmId = null;

	public SkillAlarmEmitter(AlarmRepository alarmRepo,
	                         ExecutionLogRepository execLogRepo,
	                         SchedulerHttpClient scheduler,
	                         ObjectMapper mapper) {
		this.alarmRepo = alarmRepo;
		this.execLogRepo = execLogRepo;
		this.scheduler = scheduler;
		this.mapper = mapper;
	}

	/** Snapshot of alarm-emit activity. Consumed by SystemMonitorAliasController
	 *  (via the orchestrator's delegating alarmEmitStats). */
	public Map<String, Object> stats() {
		Map<String, Object> m = new HashMap<>();
		m.put("alarms_emitted", alarmsEmitted.get());
		m.put("alarms_dedup_suppressed", alarmsDedupSuppressed.get());
		m.put("last_emit_at", lastEmitAtIso);
		m.put("last_skill", lastEmitSkillSlug);
		m.put("last_alarm_id", lastEmitAlarmId);
		return m;
	}

	/** v30.13 (2026-05-17) — write an alarms row when this run represents a
	 *  triggered patrol condition. Returns the saved entity (for SSE), or
	 *  null when guard rules block emission (test / non-patrol / dedup / no
	 *  triggered step). All exceptions caught by caller — alarm-emit must
	 *  not poison the main skill-run path. */
	// package-private for unit-test reach (v30.13b)
	AlarmEntity emitIfTriggered(SkillDocumentEntity skill,
	                            SkillRunEntity run,
	                            Map<String, Object> triggerPayload,
	                            Map<String, Object> confirmResult,
	                            List<Map<String, Object>> stepResults,
	                            boolean skipChecklist) {
		// Guard 1: tests never alarm
		if (Boolean.TRUE.equals(run.getIsTest())) return null;
		// Guard 2: only patrol stage emits (diagnose is exploratory)
		if (!"patrol".equalsIgnoreCase(skill.getStage())) return null;
		// Guard 3: confirm gate failed → no alarm
		if (skipChecklist) return null;
		// Guard 4: at least one step must have triggered (status == "pass")
		boolean anyTriggered = stepResults.stream()
				.anyMatch(s -> "pass".equalsIgnoreCase(String.valueOf(s.get("status"))));
		if (!anyTriggered) return null;

		// Pull the first evidence row up-front — we need it for BOTH the
		// equipmentId fallback (below) and the lot/step/eventTime extraction
		// further down. Cron-scheduled patrol skills don't carry a tool_id
		// in their triggerPayload, but the confirm-step's first data_view
		// typically has a `toolID` column — that's the actual machine the
		// pipeline matched against.
		Map<String, Object> evidenceRow = pickFirstEvidenceRow(confirmResult);

		// Equipment id resolution: triggerPayload first (event-driven path),
		// then evidence row's toolID (cron / patrol path), then sentinel.
		String equipmentId = triggerPayload == null ? null
				: String.valueOf(triggerPayload.getOrDefault("tool_id",
						triggerPayload.getOrDefault("equipment_id", "")));
		if (equipmentId == null || equipmentId.isBlank() || "null".equals(equipmentId)) {
			// 2026-05-23: try evidence row before sinking to "(any)" — keeps
			// alarms grouped per machine instead of dumping everything under
			// a single (any) cluster.
			if (evidenceRow != null) {
				Object t = evidenceRow.getOrDefault("toolID", evidenceRow.get("tool_id"));
				if (t != null && !String.valueOf(t).isBlank() && !"null".equals(String.valueOf(t))) {
					equipmentId = String.valueOf(t);
				}
			}
		}
		if (equipmentId == null || equipmentId.isBlank() || "null".equals(equipmentId)) {
			equipmentId = "(any)";
		}

		// Dedup: skip if active alarm exists for (skill, equipment) in last 1h
		OffsetDateTime since = OffsetDateTime.now().minus(ALARM_DEDUP_WINDOW);
		if (alarmRepo.existsActiveBySkillAndEquipmentSince(skill.getId(), equipmentId, since)) {
			alarmsDedupSuppressed.incrementAndGet();
			log.debug("skill {} run {}: alarm suppressed by dedup (active alarm "
					+ "exists for skill={}+equipment={} within {})",
					skill.getSlug(), run.getId(), skill.getId(), equipmentId, ALARM_DEDUP_WINDOW);
			return null;
		}

		// Try to extract evidence context (lot/step/event_time) from confirm
		// result's first data_view row. Best-effort — fall back to created_at
		// for event_time so AlarmClusterService (filters by event_time_after)
		// doesn't silently drop the row.
		String lotId = "";
		String step = null;
		OffsetDateTime eventTime = null;
		if (evidenceRow != null) {
			Object lot = evidenceRow.getOrDefault("lotID", evidenceRow.get("lot_id"));
			if (lot != null) lotId = String.valueOf(lot);
			Object stp = evidenceRow.get("step");
			if (stp != null) step = String.valueOf(stp);
			Object et = evidenceRow.getOrDefault("eventTime", evidenceRow.get("event_time"));
			if (et != null) eventTime = parseEvidenceTimestamp(String.valueOf(et));
		}
		// FINAL fallback: if no evidence timestamp, use now so AlarmClusterService
		// (which queries event_time, not created_at) can still find the row.
		if (eventTime == null) eventTime = OffsetDateTime.now();

		// Severity from trigger_config.severity if present; default MEDIUM
		String severity = "MEDIUM";
		Map<String, Object> trig = parseJsonObject(skill.getTriggerConfig());
		Object sev = trig.get("severity");
		if (sev != null && !String.valueOf(sev).isBlank()) {
			severity = String.valueOf(sev).toUpperCase();
		}

		// Title: skill.title + equipment
		String title = (skill.getTitle() != null ? skill.getTitle() : skill.getSlug())
				+ " — " + equipmentId;
		if (title.length() > 290) title = title.substring(0, 290);

		// Summary: lead with the human-authored description (what the gate
		// is supposed to mean), then the machine-evaluated math as
		// supporting evidence.
		//
		// 2026-05-23: alarm UX previously showed only "Confirm: 1.0 ≥ 0.0"
		// (the literal step_check math), which doesn't tell oncall what
		// the rule is for. The skill author writes a natural-language
		// intent in confirm_check.description (e.g. "5次中超過3次OOC")
		// — surface that as the headline so the trigger banner is
		// human-readable.
		Map<String, Object> confirmCheckCfg = parseJsonObject(skill.getConfirmCheck());
		Object confirmDesc = confirmCheckCfg.get("description");
		StringBuilder summary = new StringBuilder();
		if (confirmDesc != null && !String.valueOf(confirmDesc).isBlank()) {
			summary.append("條件: ").append(String.valueOf(confirmDesc).trim()).append("\n\n");
		}
		if (confirmResult != null && confirmResult.get("note") != null) {
			summary.append("Confirm: ").append(confirmResult.get("note")).append('\n');
		}
		for (Map<String, Object> s : stepResults) {
			if ("pass".equalsIgnoreCase(String.valueOf(s.get("status")))) {
				summary.append("Step ").append(s.get("step_id"))
						.append(": ").append(s.getOrDefault("note", "")).append('\n');
			}
		}
		summary.append("(SkillRun #").append(run.getId()).append(")");

		// v30.15 (2026-05-17) — write an execution_log row alongside the
		// alarm so AlarmDetail page renders findings (trigger reason +
		// evidence data_views). Without execution_log_id the detail page
		// shows the bare title/summary only — no 觸發原因 / 深度診斷.
		Long execLogId = null;
		try {
			ExecutionLogEntity exec = new ExecutionLogEntity();
			exec.setSkillId(skill.getId());
			exec.setTriggeredBy(Boolean.TRUE.equals(run.getIsTest()) ? "manual" : "agent");
			exec.setStatus("success");
			exec.setEventContext(safeJson(triggerPayload));
			exec.setLlmReadableData(buildLlmReadableData(confirmResult, stepResults, summary.toString()));
			exec.setFinishedAt(OffsetDateTime.now());
			if (run.getDurationMs() != null) exec.setDurationMs((long) run.getDurationMs());
			exec = execLogRepo.save(exec);
			execLogId = exec.getId();
		} catch (Exception ex) {
			log.warn("skill {} run {} execution_log create failed: {}",
					skill.getSlug(), run.getId(), ex.toString());
		}

		AlarmEntity a = new AlarmEntity();
		a.setSkillId(skill.getId());
		a.setTriggerEvent(deriveTriggerEvent(trig));
		a.setEquipmentId(equipmentId);
		a.setLotId(lotId);
		a.setStep(step);
		a.setEventTime(eventTime);
		a.setSeverity(severity);
		a.setTitle(title);
		a.setSummary(summary.toString());
		a.setStatus("active");
		a.setExecutionLogId(execLogId);  // v30.15: link for AlarmDetail enrichment
		a = alarmRepo.save(a);
		alarmsEmitted.incrementAndGet();
		lastEmitAtIso = OffsetDateTime.now().toString();
		lastEmitSkillSlug = skill.getSlug();
		lastEmitAlarmId = a.getId();
		log.info("skill {} run {}: emitted alarm id={} severity={} equipment={}",
				skill.getSlug(), run.getId(), a.getId(), severity, equipmentId);

		// v30.16 (2026-05-17) — fan out to auto_check pipelines (same path
		// as InternalAlarmController.create). Scheduler walks
		// pipeline_auto_check_triggers by trigger_event, runs each matched
		// auto_check pipeline, writes pb_pipeline_runs with source_alarm_id.
		// AlarmEnrichmentService picks those runs up automatically and
		// surfaces them as autoCheckRuns + diagnostic data_views in the
		// Alarm Detail page. Fail-open: dispatch failure logs but doesn't
		// break alarm emit.
		try {
			scheduler.dispatchAlarm(a.getId());
		} catch (Exception ex) {
			log.warn("skill {} run {}: dispatchAlarm(alarm={}) failed: {}",
					skill.getSlug(), run.getId(), a.getId(), ex.toString());
		}
		return a;
	}

	/** v30.15 — JSON shape AlarmEnrichmentService + AlarmDetail page expect:
	 *    findings = {
	 *      summary: "...",
	 *      condition_met: bool,
	 *      result_summary: {triggered: bool, summary: ...},
	 *      outputs: {
	 *        evidence_rows: [...rows from confirm/step data_views...],
	 *        triggered_count: N,
	 *      },
	 *      step_details: { per_step, confirm },   // NOT inside outputs (see below)
	 *      _alarm_output_schema: [...]            // tells page how to render outputs
	 *    }
	 *
	 *  <p>2026-05-23: confirm + per_step were previously under
	 *  {@code findings.outputs} where frontend RenderMiddleware would iterate
	 *  and JSON.stringify the nested objects (no schema entry tells it how to
	 *  render). UX result: alarm detail page showed raw JSON dumps for
	 *  "CONFIRM" and "PER STEP" sections. New shape stashes the same content
	 *  under {@code findings.step_details} (NOT inside {@code outputs}).
	 *  RenderMiddleware never walks step_details so no inline dump fires.
	 *  AlarmEnrichmentService walks step_details to harvest data_views into
	 *  trigger_data_views which renders as proper table via DataViewTable
	 *  component.
	 *
	 *  <p>Package-private for unit tests. */
	String buildLlmReadableData(Map<String, Object> confirmResult,
	                             List<Map<String, Object>> stepResults,
	                             String summaryText) {
		Map<String, Object> findings = new HashMap<>();
		findings.put("summary", summaryText);
		boolean triggered = stepResults.stream()
				.anyMatch(s -> "pass".equalsIgnoreCase(String.valueOf(s.get("status"))));
		findings.put("condition_met", triggered);
		findings.put("result_summary", Map.of(
				"triggered", triggered,
				"summary", summaryText
		));

		// Collect evidence rows from confirm + each step's data_views.
		// Evidence = list of rows from the FIRST data_view in confirm (the
		// canonical "what triggered" snapshot). If confirm has none, fall
		// back to step results' data_views in order.
		List<Map<String, Object>> evidenceRows = new ArrayList<>();
		List<String> evidenceColumns = new ArrayList<>();
		Map<String, Object> firstDv = pickFirstDataView(confirmResult);
		if (firstDv != null) {
			extractRowsAndCols(firstDv, evidenceRows, evidenceColumns);
		}
		if (evidenceRows.isEmpty()) {
			for (Map<String, Object> s : stepResults) {
				Map<String, Object> dv = pickFirstDataView(s);
				if (dv != null) {
					extractRowsAndCols(dv, evidenceRows, evidenceColumns);
					if (!evidenceRows.isEmpty()) break;
				}
			}
		}

		Map<String, Object> perStep = new HashMap<>();
		for (Map<String, Object> s : stepResults) {
			Map<String, Object> entry = new HashMap<>();
			entry.put("status", s.get("status"));
			entry.put("note", s.get("note"));
			entry.put("value", s.get("value"));
			entry.put("data_views", s.get("data_views"));
			perStep.put(String.valueOf(s.get("step_id")), entry);
		}

		Map<String, Object> outputs = new HashMap<>();
		outputs.put("evidence_rows", evidenceRows);
		outputs.put("triggered_count", evidenceRows.size());
		findings.put("outputs", outputs);

		Map<String, Object> stepDetails = new HashMap<>();
		stepDetails.put("per_step", perStep);
		if (confirmResult != null) stepDetails.put("confirm", confirmResult);
		findings.put("step_details", stepDetails);

		// Output schema override — tells AlarmDetail page how to render
		// outputs.evidence_rows (as a table with these columns) and
		// outputs.triggered_count (as a scalar).
		List<Map<String, Object>> schema = new ArrayList<>();
		Map<String, Object> evSchema = new HashMap<>();
		evSchema.put("key", "evidence_rows");
		evSchema.put("type", "table");
		evSchema.put("label", "觸發證據 (data rows that matched the condition)");
		List<Map<String, String>> cols = new ArrayList<>();
		int added = 0;
		for (String col : evidenceColumns) {
			if (added >= 8) break;
			Map<String, String> c = new HashMap<>();
			c.put("key", col); c.put("label", col);
			cols.add(c);
			added++;
		}
		evSchema.put("columns", cols);
		schema.add(evSchema);
		Map<String, Object> tcSchema = new HashMap<>();
		tcSchema.put("key", "triggered_count");
		tcSchema.put("type", "scalar");
		tcSchema.put("label", "觸發筆數");
		tcSchema.put("unit", "rows");
		schema.add(tcSchema);
		findings.put("_alarm_output_schema", schema);

		return safeJson(findings);
	}

	// ── Helpers (package-private where tests reach) ────────────────────────

	/** Extract rows + columns from a data_view dict. Idempotent on empty/missing. */
	@SuppressWarnings("unchecked")
	private void extractRowsAndCols(Map<String, Object> dv,
	                                 List<Map<String, Object>> rowsOut,
	                                 List<String> colsOut) {
		Object rows = dv.get("rows");
		if (rows instanceof List<?> rowList) {
			for (Object r : rowList) {
				if (r instanceof Map) rowsOut.add((Map<String, Object>) r);
			}
		}
		Object cols = dv.get("columns");
		if (cols instanceof List<?> colList) {
			for (Object c : colList) {
				if (c != null) colsOut.add(String.valueOf(c));
			}
		}
	}

	/** Pick first data_view from a confirm/step result map. */
	@SuppressWarnings("unchecked")
	private Map<String, Object> pickFirstDataView(Map<String, Object> result) {
		if (result == null) return null;
		Object dvs = result.get("data_views");
		if (!(dvs instanceof List<?> list) || list.isEmpty()) return null;
		Object first = list.get(0);
		return first instanceof Map ? (Map<String, Object>) first : null;
	}

	/** Read confirm result's first data_view row, if any. Tolerant of shape.
	 *  Package-private for unit tests. */
	@SuppressWarnings("unchecked")
	Map<String, Object> pickFirstEvidenceRow(Map<String, Object> confirmResult) {
		if (confirmResult == null) return null;
		Object dvs = confirmResult.get("data_views");
		if (!(dvs instanceof List<?> dvList) || dvList.isEmpty()) return null;
		Object first = dvList.get(0);
		if (!(first instanceof Map<?, ?> dv)) return null;
		Object rows = ((Map<String, Object>) dv).get("rows");
		if (!(rows instanceof List<?> rowList) || rowList.isEmpty()) return null;
		Object row0 = rowList.get(0);
		return row0 instanceof Map ? (Map<String, Object>) row0 : null;
	}

	/** Parse evidence timestamp tolerantly. Accepts:
	 *   2026-05-17T00:21:13.505000+00:00  (ISO with offset)
	 *   2026-05-17T00:21:13.505000        (ISO no offset → assume UTC)
	 *   2026-05-17T00:21:13               (ISO no fraction)
	 *  Returns null if unparseable. Package-private for unit tests. */
	static OffsetDateTime parseEvidenceTimestamp(String raw) {
		if (raw == null || raw.isBlank() || "null".equals(raw)) return null;
		try { return OffsetDateTime.parse(raw); } catch (Exception ignored) {}
		try {
			LocalDateTime ldt = LocalDateTime.parse(raw, DateTimeFormatter.ISO_LOCAL_DATE_TIME);
			return ldt.atOffset(ZoneOffset.UTC);
		} catch (Exception ignored) {}
		return null;
	}

	// package-private for unit tests
	String deriveTriggerEvent(Map<String, Object> triggerConfig) {
		if (triggerConfig == null || triggerConfig.isEmpty()) return ALARM_TRIGGER_EVENT_PATROL;
		Object type = triggerConfig.get("type");
		if ("event".equals(type)) {
			Object ev = triggerConfig.get("event");
			if (ev != null && !String.valueOf(ev).isBlank()) return String.valueOf(ev);
		}
		return ALARM_TRIGGER_EVENT_PATROL;
	}

	private Map<String, Object> parseJsonObject(String json) {
		if (json == null || json.isBlank()) return Map.of();
		try {
			return mapper.readValue(json, JSON_MAP_TYPE);
		} catch (Exception e) {
			return Map.of();
		}
	}

	private String safeJson(Object o) {
		if (o == null) return null;
		try { return mapper.writeValueAsString(o); }
		catch (Exception ex) { return null; }
	}
}
