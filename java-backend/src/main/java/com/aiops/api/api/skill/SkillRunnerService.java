package com.aiops.api.api.skill;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.skill.ExecutionLogEntity;
import com.aiops.api.domain.skill.ExecutionLogRepository;
import com.aiops.api.domain.skill.SkillDocumentEntity;
import com.aiops.api.domain.skill.SkillDocumentRepository;
import com.aiops.api.domain.skill.SkillRunEntity;
import com.aiops.api.domain.skill.SkillRunRepository;
import com.aiops.api.sidecar.PythonSidecarClient;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Sinks;
import reactor.core.scheduler.Schedulers;

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
 * Phase 11-C — SkillRunner.
 *
 * <p>Runs all steps of a Skill Document sequentially. Each step has a
 * {@code pipeline_id} pointing to {@code pb_pipelines}; we forward the
 * trigger_payload as inputs to the sidecar's pipeline executor and read
 * the {@code block_step_check} output ({@code pass / value / note}) to
 * decide step pass/fail.
 *
 * <p>Per E5 (user decision): steps don't short-circuit on failure — every
 * step runs regardless of upstream verdict, so SummaryReport surfaces
 * all findings at once.
 *
 * <p>Sandbox flag ({@code is_test}) flows through to {@link SkillRunEntity}
 * so stats roll-ups can exclude test runs.
 */
@Slf4j
@Service
public class SkillRunnerService {

    private static final TypeReference<List<Map<String, Object>>> JSON_LIST_TYPE = new TypeReference<>() {};
    private static final TypeReference<Map<String, Object>> JSON_MAP_TYPE = new TypeReference<>() {};

    private final SkillDocumentRepository skillRepo;
    private final SkillRunRepository runRepo;
    private final PipelineRepository pipelineRepo;
    private final PythonSidecarClient sidecar;
    private final ObjectMapper mapper;
    private final AlarmRepository alarmRepo;
    private final ExecutionLogRepository execLogRepo;

    public SkillRunnerService(SkillDocumentRepository skillRepo,
                              SkillRunRepository runRepo,
                              PipelineRepository pipelineRepo,
                              PythonSidecarClient sidecar,
                              ObjectMapper mapper,
                              AlarmRepository alarmRepo,
                              ExecutionLogRepository execLogRepo) {
        this.skillRepo = skillRepo;
        this.runRepo = runRepo;
        this.pipelineRepo = pipelineRepo;
        this.sidecar = sidecar;
        this.mapper = mapper;
        this.alarmRepo = alarmRepo;
        this.execLogRepo = execLogRepo;
    }

    /** v30.13 — emit-alarm guard: skip non-patrol stages + 1-hour dedup window. */
    private static final Duration ALARM_DEDUP_WINDOW = Duration.ofHours(1);
    private static final String ALARM_TRIGGER_EVENT_PATROL = "patrol_check";

    /** v30.13b (2026-05-17) — in-memory counters surfaced via System Monitor.
     *  Reset on JVM restart (acceptable — service runs as long-lived systemd
     *  unit; restart cadence is human-driven). For persistent metrics, query
     *  alarms / skill_runs tables directly. */
    private final AtomicLong alarmsEmitted = new AtomicLong(0);
    private final AtomicLong alarmsDedupSuppressed = new AtomicLong(0);
    private volatile String lastEmitAtIso = null;
    private volatile String lastEmitSkillSlug = null;
    private volatile Long lastEmitAlarmId = null;

    /** Snapshot of alarm-emit activity. Consumed by SystemMonitorAliasController. */
    public Map<String, Object> alarmEmitStats() {
        Map<String, Object> m = new HashMap<>();
        m.put("alarms_emitted", alarmsEmitted.get());
        m.put("alarms_dedup_suppressed", alarmsDedupSuppressed.get());
        m.put("last_emit_at", lastEmitAtIso);
        m.put("last_skill", lastEmitSkillSlug);
        m.put("last_alarm_id", lastEmitAlarmId);
        return m;
    }

    /** Reactive stream of SSE-shaped events; controller bridges into SseEmitter. */
    public Flux<RunEvent> run(String slug,
                              Map<String, Object> triggerPayload,
                              boolean isTest,
                              AuthPrincipal caller) {
        SkillDocumentEntity skill = skillRepo.findBySlug(slug).orElse(null);
        if (skill == null) {
            return Flux.just(RunEvent.error("skill not found: " + slug));
        }

        Sinks.Many<RunEvent> sink = Sinks.many().unicast().onBackpressureBuffer();

        // Fire-and-forget the actual execution on the elastic scheduler so we
        // can return the Flux immediately. Each step's sidecar call is sync
        // (block on the Mono) — keeps the per-step ordering explicit.
        Flux.fromIterable(parseSteps(skill.getSteps()))
                .publishOn(Schedulers.boundedElastic())
                .doOnSubscribe(s -> {
                    SkillRunEntity run = createRunRow(skill.getId(), triggerPayload, isTest);
                    sink.tryEmitNext(RunEvent.start(skill.getSlug(), run.getId(), parseSteps(skill.getSteps()).size()));
                    runWithSink(skill, run, triggerPayload, sink, caller);
                })
                .subscribe();

        return sink.asFlux();
    }

    private void runWithSink(SkillDocumentEntity skill,
                             SkillRunEntity run,
                             Map<String, Object> triggerPayload,
                             Sinks.Many<RunEvent> sink,
                             AuthPrincipal caller) {
        long started = System.currentTimeMillis();
        List<Map<String, Object>> steps = parseSteps(skill.getSteps());
        List<Map<String, Object>> stepResults = new ArrayList<>();

        // Phase 11 v2 — CONFIRM step (optional gate). If present and fails,
        // skip the entire CHECKLIST and mark run "skipped_by_confirm" so
        // downstream materializers don't write an alarm.
        Map<String, Object> confirmConfig = parseJsonObject(skill.getConfirmCheck());
        boolean skipChecklist = false;
        Map<String, Object> confirmResult = null;
        if (!confirmConfig.isEmpty()) {
            Number cpId = (Number) confirmConfig.get("pipeline_id");
            Long confirmPipelineId = cpId != null ? cpId.longValue() : null;
            sink.tryEmitNext(RunEvent.confirmStart());
            if (confirmPipelineId == null) {
                confirmResult = stepResultPending("confirm", "no confirm pipeline bound");
            } else {
                confirmResult = runOneStep("confirm", confirmPipelineId, triggerPayload, caller);
            }
            sink.tryEmitNext(RunEvent.confirmDone(confirmResult));
            boolean mustPass = !Boolean.FALSE.equals(confirmConfig.get("must_pass"));
            String confirmStatus = String.valueOf(confirmResult.get("status"));
            if (mustPass && !"pass".equals(confirmStatus)) {
                skipChecklist = true;
            }
        }

        if (!skipChecklist) {
            for (Map<String, Object> step : steps) {
                String stepId = String.valueOf(step.get("id"));
                Number pipelineIdNum = (Number) step.get("pipeline_id");
                Long pipelineId = pipelineIdNum != null ? pipelineIdNum.longValue() : null;

                sink.tryEmitNext(RunEvent.stepStart(stepId));

                Map<String, Object> stepResult;
                if (pipelineId == null) {
                    stepResult = stepResultPending(stepId, "no pipeline bound");
                } else {
                    stepResult = runOneStep(stepId, pipelineId, triggerPayload, caller);
                }
                stepResults.add(stepResult);
                sink.tryEmitNext(RunEvent.stepDone(stepResult));
            }
        }

        run.setStatus(skipChecklist ? "skipped_by_confirm" : "completed");
        run.setFinishedAt(OffsetDateTime.now());
        run.setDurationMs((int) (System.currentTimeMillis() - started));
        try {
            // Persist confirm result alongside step_results for replay UI.
            Map<String, Object> persisted = new HashMap<>();
            persisted.put("steps", stepResults);
            if (confirmResult != null) persisted.put("confirm", confirmResult);
            run.setStepResults(mapper.writeValueAsString(persisted));
        } catch (Exception e) {
            run.setStepResults("[]");
        }
        runRepo.save(run);

        // Phase 11-D — refresh stats on the skill (excludes test runs from
        // counters; test runs still recorded for historical replay but
        // mustn't pollute marketplace metrics).
        if (Boolean.FALSE.equals(run.getIsTest())) {
            updateSkillStats(skill, run);
        }

        // v30.13 (2026-05-17) — alarm-emit chain. SkillRunner is the only
        // place that knows "step_check.pass=true + skill stage=patrol" → an
        // alarm row should exist. Without this, Alarm Center is permanently
        // empty even when patrol skills run and detect anomalies.
        try {
            AlarmEntity alarm = emitAlarmIfTriggered(
                    skill, run, triggerPayload, confirmResult, stepResults, skipChecklist);
            if (alarm != null) {
                sink.tryEmitNext(RunEvent.alarmCreated(alarm));
            }
        } catch (Exception ex) {  // never let alarm-emit fail the main run
            log.warn("skill {} run {} alarm-emit failed: {}",
                    skill.getSlug(), run.getId(), ex.toString());
        }

        sink.tryEmitNext(RunEvent.done(run.getId(), stepResults));
        sink.tryEmitComplete();
    }

    /** v30.13 (2026-05-17) — write an alarms row when this run represents a
     *  triggered patrol condition. Returns the saved entity (for SSE), or
     *  null when guard rules block emission (test / non-patrol / dedup / no
     *  triggered step). All exceptions caught by caller — alarm-emit must
     *  not poison the main skill-run path.
     */
    // package-private for unit-test reach (v30.13b)
    AlarmEntity emitAlarmIfTriggered(SkillDocumentEntity skill,
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

        // Equipment id from trigger_payload (patrol may not have one — use sentinel)
        String equipmentId = triggerPayload == null ? null
                : String.valueOf(triggerPayload.getOrDefault("tool_id",
                                  triggerPayload.getOrDefault("equipment_id", "")));
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
        Map<String, Object> evidenceRow = pickFirstEvidenceRow(confirmResult);
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

        // Summary: consolidate confirm.note + passing step notes
        StringBuilder summary = new StringBuilder();
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
            ExecutionLogEntity log = new ExecutionLogEntity();
            log.setSkillId(skill.getId());
            log.setTriggeredBy(Boolean.TRUE.equals(run.getIsTest()) ? "manual" : "agent");
            log.setStatus("success");
            log.setEventContext(safeJson(triggerPayload));
            log.setLlmReadableData(buildLlmReadableData(confirmResult, stepResults, summary.toString()));
            log.setFinishedAt(OffsetDateTime.now());
            if (run.getDurationMs() != null) log.setDurationMs((long) run.getDurationMs());
            log = execLogRepo.save(log);
            execLogId = log.getId();
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
     *        per_step: {sN: {status, note, data_views}}
     *      },
     *      _alarm_output_schema: [...]   // tells page how to render outputs
     *    }
     *  package-private for unit tests.
     */
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
        outputs.put("per_step", perStep);
        if (confirmResult != null) outputs.put("confirm", confirmResult);
        findings.put("outputs", outputs);

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

    private String safeJson(Object o) {
        if (o == null) return null;
        try { return mapper.writeValueAsString(o); }
        catch (Exception ex) { return null; }
    }

    /** Parse evidence timestamp tolerantly. Accepts:
     *   2026-05-17T00:21:13.505000+00:00  (ISO with offset)
     *   2026-05-17T00:21:13.505000        (ISO no offset → assume UTC)
     *   2026-05-17T00:21:13               (ISO no fraction)
     *  Returns null if unparseable. package-private for unit tests. */
    static OffsetDateTime parseEvidenceTimestamp(String raw) {
        if (raw == null || raw.isBlank() || "null".equals(raw)) return null;
        try { return OffsetDateTime.parse(raw); } catch (Exception ignored) {}
        try {
            LocalDateTime ldt = LocalDateTime.parse(raw, DateTimeFormatter.ISO_LOCAL_DATE_TIME);
            return ldt.atOffset(ZoneOffset.UTC);
        } catch (Exception ignored) {}
        return null;
    }

    /** Read confirm result's first data_view row, if any. Tolerant of shape.
     *  package-private for unit tests. */
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

    @Transactional
    void updateSkillStats(SkillDocumentEntity skill, SkillRunEntity lastRun) {
        try {
            Map<String, Object> stats;
            try {
                stats = new HashMap<>(skill.getStats() == null || skill.getStats().isBlank()
                        ? Map.of()
                        : mapper.readValue(skill.getStats(), JSON_MAP_TYPE));
            } catch (Exception e) {
                stats = new HashMap<>();
            }
            int prevTotal = stats.get("runs_total") instanceof Number n ? n.intValue() : 0;
            stats.put("runs_total", prevTotal + 1);
            stats.put("last_run_at", lastRun.getTriggeredAt() != null
                    ? lastRun.getTriggeredAt().toString() : OffsetDateTime.now().toString());

            // runs_30d — count via repo query
            OffsetDateTime since = OffsetDateTime.now().minusDays(30);
            long runs30d = runRepo.countNonTestSince(skill.getId(), since);
            stats.put("runs_30d", runs30d);

            skill.setStats(mapper.writeValueAsString(stats));
            skillRepo.save(skill);
        } catch (Exception e) {
            log.warn("skill {} stats update failed: {}", skill.getSlug(), e.toString());
        }
    }

    private Map<String, Object> runOneStep(String stepId,
                                            Long pipelineId,
                                            Map<String, Object> payload,
                                            AuthPrincipal caller) {
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

            @SuppressWarnings("rawtypes")
            Map result = sidecar.postJson("/internal/pipeline/execute", body, Map.class, caller)
                    .block(Duration.ofSeconds(60));
            return parseRunResult(stepId, result, System.currentTimeMillis() - t0);
        } catch (Exception ex) {
            log.warn("step {} pipeline {} crashed: {}", stepId, pipelineId, ex.toString());
            return stepResultError(stepId, ex.getClass().getSimpleName() + ": " + ex.getMessage());
        }
    }

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
     *  author marked with `block_data_view` nodes, NOT every intermediate
     *  dataframe. Sidecar already does this work in
     *  {@code _collect_data_view_summaries} → exposed at
     *  {@code result.result_summary.data_views}. We just pass it through.
     *  Caps cols/rows to keep SSE payload bounded. */
    @SuppressWarnings({"unchecked", "rawtypes"})
    private List<Map<String, Object>> extractDataViews(Map<String, Object> result, Map<String, Object> nodeResults) {
        final int MAX_ROWS = 20;
        final int MAX_COLS = 8;
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
                        view.put("columns", ((List<Object>) cl).subList(0, Math.min(cl.size(), MAX_COLS)));
                    } else {
                        view.put("columns", List.of());
                    }
                    if (rows instanceof List<?> rl) {
                        view.put("rows", ((List<Object>) rl).subList(0, Math.min(rl.size(), MAX_ROWS)));
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
        java.util.Set<String> terminals = new java.util.HashSet<>();
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
                    view.put("columns", cols.subList(0, Math.min(cols.size(), MAX_COLS)));
                    view.put("rows", rows.subList(0, Math.min(rows.size(), MAX_ROWS)));
                    view.put("total", totalObj instanceof Number n ? n.intValue() : rows.size());
                    return List.of(view);   // only one fallback view
                }
            }
        }
        return List.of();
    }

    private List<Map<String, Object>> parseSteps(String json) {
        try {
            return mapper.readValue(json == null || json.isBlank() ? "[]" : json, JSON_LIST_TYPE);
        } catch (Exception e) {
            return List.of();
        }
    }

    @Transactional
    SkillRunEntity createRunRow(Long skillId, Map<String, Object> payload, boolean isTest) {
        SkillRunEntity r = new SkillRunEntity();
        r.setSkillId(skillId);
        r.setIsTest(isTest);
        r.setTriggeredBy(isTest ? "user_test" : "manual");
        try {
            r.setTriggerPayload(mapper.writeValueAsString(payload != null ? payload : Map.of()));
        } catch (Exception e) {
            r.setTriggerPayload("{}");
        }
        return runRepo.save(r);
    }

    private Map<String, Object> stepResultError(String stepId, String msg) {
        Map<String, Object> sr = new HashMap<>();
        sr.put("step_id", stepId);
        sr.put("status", "fail");
        sr.put("value", "error");
        sr.put("note", msg);
        return sr;
    }

    private Map<String, Object> stepResultPending(String stepId, String reason) {
        Map<String, Object> sr = new HashMap<>();
        sr.put("step_id", stepId);
        sr.put("status", "skipped");
        sr.put("value", "—");
        sr.put("note", reason);
        return sr;
    }

    /** Wire-format: SSE events the controller renders. */
    public record RunEvent(String type, Map<String, Object> data) {
        static RunEvent start(String slug, Long runId, int stepCount) {
            return new RunEvent("run_start", Map.of("slug", slug, "run_id", runId, "step_count", stepCount));
        }
        static RunEvent stepStart(String stepId) {
            return new RunEvent("step_start", Map.of("step_id", stepId));
        }
        static RunEvent stepDone(Map<String, Object> result) {
            return new RunEvent("step_done", result);
        }
        static RunEvent confirmStart() {
            return new RunEvent("confirm_start", Map.of());
        }
        static RunEvent confirmDone(Map<String, Object> result) {
            return new RunEvent("confirm_done", result);
        }
        static RunEvent done(Long runId, List<Map<String, Object>> stepResults) {
            return new RunEvent("done", Map.of("run_id", runId, "step_results", stepResults));
        }
        static RunEvent error(String message) {
            return new RunEvent("error", Map.of("message", message));
        }
        /** v30.13 (2026-05-17) — alarm-emit notification so UI can refresh
         *  Alarm Center without polling. Carries the new alarm id + summary
         *  fields, not the full entity (avoid JPA-Jackson cycles). */
        static RunEvent alarmCreated(AlarmEntity a) {
            Map<String, Object> data = new HashMap<>();
            data.put("alarm_id", a.getId());
            data.put("severity", a.getSeverity());
            data.put("title", a.getTitle());
            data.put("equipment_id", a.getEquipmentId());
            data.put("skill_id", a.getSkillId());
            return new RunEvent("alarm_created", data);
        }
    }
}
