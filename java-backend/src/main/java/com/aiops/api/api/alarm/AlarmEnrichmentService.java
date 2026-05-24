package com.aiops.api.api.alarm;

import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.pipeline.PipelineRunEntity;
import com.aiops.api.domain.pipeline.PipelineRunRepository;
import com.aiops.api.domain.skill.ExecutionLogEntity;
import com.aiops.api.domain.skill.ExecutionLogRepository;
import com.aiops.api.domain.skill.SkillDefinitionEntity;
import com.aiops.api.domain.skill.SkillDefinitionRepository;
import com.aiops.api.domain.skill.SkillDocumentEntity;
import com.aiops.api.domain.skill.SkillDocumentRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.*;
import java.util.stream.Collectors;
import java.util.stream.StreamSupport;

/**
 * Batches the extra lookups that the Alarm Center page expects in its list +
 * detail response: {@code findings} (from execution_log.llm_readable_data),
 * {@code output_schema} (from skill.output_schema), and the
 * {@code diagnostic_results[]} list (execution_logs triggered by this alarm).
 *
 * <p>Python returned all of this inline in the list endpoint. A naive port
 * would do N+3 queries per alarm; instead we do 3 bulk queries per page.
 */
@Service
public class AlarmEnrichmentService {

	private static final Logger log = LoggerFactory.getLogger(AlarmEnrichmentService.class);

	private final ExecutionLogRepository execLogRepo;
	private final SkillDefinitionRepository skillRepo;
	private final SkillDocumentRepository skillDocRepo;
	private final PipelineRunRepository pipelineRunRepo;
	private final PipelineRepository pipelineRepo;
	private final ObjectMapper mapper;
	private final ChartMiddleware chartMiddleware;

	public AlarmEnrichmentService(ExecutionLogRepository execLogRepo,
	                              SkillDefinitionRepository skillRepo,
	                              SkillDocumentRepository skillDocRepo,
	                              PipelineRunRepository pipelineRunRepo,
	                              PipelineRepository pipelineRepo,
	                              ObjectMapper mapper,
	                              ChartMiddleware chartMiddleware) {
		this.execLogRepo = execLogRepo;
		this.skillRepo = skillRepo;
		this.skillDocRepo = skillDocRepo;
		this.pipelineRunRepo = pipelineRunRepo;
		this.pipelineRepo = pipelineRepo;
		this.mapper = mapper;
		this.chartMiddleware = chartMiddleware;
	}

	public List<AlarmDtos.Summary> enrichSummaries(List<AlarmEntity> alarms) {
		if (alarms.isEmpty()) return List.of();
		Ctx ctx = loadContext(alarms);
		return alarms.stream().map(a -> buildSummary(a, ctx)).toList();
	}

	public AlarmDtos.Detail enrichDetail(AlarmEntity alarm) {
		Ctx ctx = loadContext(List.of(alarm));
		return buildDetail(alarm, ctx);
	}

	private Ctx loadContext(List<AlarmEntity> alarms) {
		// Collect ids we need to batch-fetch
		Set<Long> execIds = new HashSet<>();
		Set<Long> skillIds = new HashSet<>();
		List<String> triggerKeys = new ArrayList<>();
		List<String> alarmIdTexts = new ArrayList<>();
		for (AlarmEntity a : alarms) {
			if (a.getExecutionLogId() != null) execIds.add(a.getExecutionLogId());
			if (a.getDiagnosticLogId() != null) execIds.add(a.getDiagnosticLogId());
			if (a.getSkillId() != null) skillIds.add(a.getSkillId());
			triggerKeys.add("alarm:" + a.getId());
			if (a.getId() != null) alarmIdTexts.add(String.valueOf(a.getId()));
		}

		// Pull diagnostic exec logs; their skill_ids also need to be in the skill map.
		List<ExecutionLogEntity> diagLogs = triggerKeys.isEmpty()
				? List.of()
				: execLogRepo.findByTriggeredByInOrderByStartedAtDesc(triggerKeys);
		for (ExecutionLogEntity dl : diagLogs) {
			if (dl.getId() != null) execIds.add(dl.getId());
			if (dl.getSkillId() != null) skillIds.add(dl.getSkillId());
		}

		Map<Long, ExecutionLogEntity> execsById = execIds.isEmpty()
				? Map.of()
				: StreamSupport.stream(execLogRepo.findAllById(execIds).spliterator(), false)
				.collect(Collectors.toMap(ExecutionLogEntity::getId, x -> x, (a, b) -> a));

		Map<Long, SkillDefinitionEntity> skillsById = skillIds.isEmpty()
				? Map.of()
				: StreamSupport.stream(skillRepo.findAllById(skillIds).spliterator(), false)
				.collect(Collectors.toMap(SkillDefinitionEntity::getId, x -> x, (a, b) -> a));

		// Group diagnostic logs by alarm id
		Map<Long, List<ExecutionLogEntity>> diagsByAlarmId = new HashMap<>();
		for (ExecutionLogEntity dl : diagLogs) {
			Long aid = parseAlarmIdFromTrigger(dl.getTriggeredBy());
			if (aid != null) diagsByAlarmId.computeIfAbsent(aid, k -> new ArrayList<>()).add(dl);
		}

		// One bulk JSONB scan instead of N. Group by source_alarm_id parsed
		// from each run's node_results. Pipeline names also batched.
		Map<Long, List<PipelineRunEntity>> runsByAlarmId = new HashMap<>();
		Map<Long, String> pipelineNameById = Map.of();
		if (!alarmIdTexts.isEmpty()) {
			List<PipelineRunEntity> runs;
			try {
				runs = pipelineRunRepo.findAllByAlarmIds(alarmIdTexts);
			} catch (RuntimeException ex) {
				log.warn("alarm enrichment: batch run lookup failed: {}", ex.toString());
				runs = List.of();
			}
			Set<Long> pipelineIds = new LinkedHashSet<>();
			for (PipelineRunEntity r : runs) {
				JsonNode runNode = parseJsonNode(r.getNodeResults());
				Long aid = parseSourceAlarmId(runNode);
				if (aid != null) {
					runsByAlarmId.computeIfAbsent(aid, k -> new ArrayList<>()).add(r);
				}
				if (r.getPipelineId() != null) pipelineIds.add(r.getPipelineId());
			}
			if (!pipelineIds.isEmpty()) {
				pipelineNameById = StreamSupport.stream(
						pipelineRepo.findAllById(pipelineIds).spliterator(), false)
						.collect(Collectors.toMap(
								PipelineEntity::getId, PipelineEntity::getName, (x, y) -> x));
			}
		}

		return new Ctx(execsById, skillsById, diagsByAlarmId, runsByAlarmId, pipelineNameById);
	}

	private static Long parseSourceAlarmId(JsonNode runNode) {
		if (runNode == null) return null;
		JsonNode v = runNode.get("source_alarm_id");
		if (v == null || v.isNull()) return null;
		if (v.isNumber()) return v.asLong();
		try { return Long.parseLong(v.asText().trim()); }
		catch (NumberFormatException e) { return null; }
	}

	private AlarmDtos.Summary buildSummary(AlarmEntity a, Ctx ctx) {
		EnrichedFields f = buildFields(a, ctx);
		return new AlarmDtos.Summary(
				a.getId(), a.getSkillId(), a.getTriggerEvent(), a.getEquipmentId(),
				a.getLotId(), a.getStep(), a.getSeverity(), a.getStatus(), a.getTitle(),
				a.getSummary(), a.getEventTime(), a.getCreatedAt(),
				a.getAcknowledgedBy(), a.getAcknowledgedAt(), a.getResolvedAt(),
				a.getExecutionLogId(), a.getDiagnosticLogId(),
				f.findings, f.outputSchema, f.diagnosticFindings, f.diagnosticOutputSchema,
				f.charts,
				f.diagnosticResults,
				f.triggerDataViews, f.diagnosticDataViews,
				f.diagnosticCharts, f.diagnosticAlert,
				f.autoCheckRuns,
				a.getAckedBy(), a.getAckedAt(),
				a.getDisposition(), a.getDispositionReason(),
				a.getDisposedBy(), a.getDisposedAt());
	}

	private AlarmDtos.Detail buildDetail(AlarmEntity a, Ctx ctx) {
		EnrichedFields f = buildFields(a, ctx);
		return new AlarmDtos.Detail(
				a.getId(), a.getSkillId(), a.getTriggerEvent(), a.getEquipmentId(),
				a.getLotId(), a.getStep(), a.getEventTime(), a.getSeverity(),
				a.getTitle(), a.getSummary(), a.getStatus(),
				a.getAcknowledgedBy(), a.getAcknowledgedAt(), a.getResolvedAt(),
				a.getExecutionLogId(), a.getDiagnosticLogId(), a.getCreatedAt(),
				f.findings, f.outputSchema, f.diagnosticFindings, f.diagnosticOutputSchema,
				f.charts,
				f.diagnosticResults,
				f.triggerDataViews, f.diagnosticDataViews,
				f.diagnosticCharts, f.diagnosticAlert,
				f.autoCheckRuns,
				a.getAckedBy(), a.getAckedAt(),
				a.getDisposition(), a.getDispositionReason(),
				a.getDisposedBy(), a.getDisposedAt());
	}

	private EnrichedFields buildFields(AlarmEntity a, Ctx ctx) {
		ExecutionLogEntity execLog = a.getExecutionLogId() != null ? ctx.execs.get(a.getExecutionLogId()) : null;
		ExecutionLogEntity diagLog = a.getDiagnosticLogId() != null ? ctx.execs.get(a.getDiagnosticLogId()) : null;
		SkillDefinitionEntity skill = a.getSkillId() != null ? ctx.skills.get(a.getSkillId()) : null;

		Object findings = execLog != null ? parseJson(execLog.getLlmReadableData()) : null;
		Object outputSchema = skill != null ? parseJson(skill.getOutputSchema()) : null;
		List<Object> charts = List.of();

		// Pipeline-backed patrols set skill_id=NULL on the alarm (no linked
		// skill), so the skill-derived output_schema is empty and the alarm
		// page falls back to raw-JSON-dumping findings.outputs. Honor the
		// pipeline's self-declared schema + charts stored alongside findings.
		if (findings instanceof JsonNode fn && fn.isObject()) {
			JsonNode schemaOverride = fn.get("_alarm_output_schema");
			if (schemaOverride != null && schemaOverride.isArray() && schemaOverride.size() > 0) {
				outputSchema = schemaOverride;
			}
			JsonNode chartsOverride = fn.get("_alarm_charts");
			if (chartsOverride != null && chartsOverride.isArray()) {
				List<Object> list = new java.util.ArrayList<>();
				chartsOverride.forEach(list::add);
				charts = list;
			}
			// Back-compat for alarms (5813–5838) written before the
			// schema-override fix — their outputs are {pipeline_id,
			// result_summary, evidence} with no schema. Map them into
			// the same {evidence_rows, triggered_count} shape the new
			// path emits, so the alarm page renders identically.
			JsonNode outputsNode = fn.get("outputs");
			boolean hasOverride = schemaOverride != null && schemaOverride.isArray()
					&& schemaOverride.size() > 0;
			if (!hasOverride && outputsNode != null && outputsNode.isObject()
					&& outputsNode.has("evidence") && outputsNode.has("pipeline_id")) {
				JsonNode evidence = outputsNode.get("evidence");
				JsonNode rowsNode = evidence != null ? evidence.get("rows") : null;
				JsonNode columnsNode = evidence != null ? evidence.get("columns") : null;
				JsonNode totalNode = evidence != null ? evidence.get("total") : null;
				if (rowsNode != null && rowsNode.isArray()) {
					com.fasterxml.jackson.databind.node.ObjectNode synthesizedOutputs =
							mapper.createObjectNode();
					synthesizedOutputs.set("evidence_rows", rowsNode);
					synthesizedOutputs.put("triggered_count",
							totalNode != null && totalNode.isNumber()
									? totalNode.asInt() : rowsNode.size());
					((com.fasterxml.jackson.databind.node.ObjectNode) fn)
							.set("outputs", synthesizedOutputs);

					com.fasterxml.jackson.databind.node.ArrayNode synthesizedSchema =
							mapper.createArrayNode();
					com.fasterxml.jackson.databind.node.ObjectNode evSchema =
							mapper.createObjectNode();
					evSchema.put("key", "evidence_rows");
					evSchema.put("type", "table");
					evSchema.put("label", "觸發證據（最近觸發的 row）");
					if (columnsNode != null && columnsNode.isArray()) {
						com.fasterxml.jackson.databind.node.ArrayNode cols =
								mapper.createArrayNode();
						java.util.Set<String> skip = java.util.Set.of(
								"triggered_row", "violation_side");
						int added = 0;
						for (JsonNode col : columnsNode) {
							if (added >= 8) break;
							String cn = col.asText();
							if (skip.contains(cn)) continue;
							com.fasterxml.jackson.databind.node.ObjectNode c =
									mapper.createObjectNode();
							c.put("key", cn);
							c.put("label", cn);
							cols.add(c);
							added++;
						}
						evSchema.set("columns", cols);
					}
					synthesizedSchema.add(evSchema);
					com.fasterxml.jackson.databind.node.ObjectNode tcSchema =
							mapper.createObjectNode();
					tcSchema.put("key", "triggered_count");
					tcSchema.put("type", "scalar");
					tcSchema.put("label", "觸發筆數");
					tcSchema.put("unit", "筆");
					synthesizedSchema.add(tcSchema);
					outputSchema = synthesizedSchema;
				}
			}
		}

		Object diagFindings = diagLog != null ? parseJson(diagLog.getLlmReadableData()) : null;
		Object diagOutputSchema = null;
		if (diagLog != null && diagLog.getSkillId() != null) {
			SkillDefinitionEntity ds = ctx.skills.get(diagLog.getSkillId());
			if (ds != null) diagOutputSchema = parseJson(ds.getOutputSchema());
		}

		List<AlarmDtos.DiagnosticResult> diagnosticResults = Optional
				.ofNullable(ctx.diagsByAlarmId.get(a.getId()))
				.orElse(List.of())
				.stream()
				.map(dl -> {
					SkillDefinitionEntity s = dl.getSkillId() != null ? ctx.skills.get(dl.getSkillId()) : null;
					Object drFindings = parseJson(dl.getLlmReadableData());
					Object drOutputSchema = s != null ? parseJson(s.getOutputSchema()) : null;
					List<Object> drCharts = List.of();
					if (drFindings instanceof JsonNode fJson && drOutputSchema instanceof JsonNode osJson) {
						try { drCharts = chartMiddleware.buildCharts(fJson, osJson); }
						catch (RuntimeException ex) { log.warn("chart-middleware failed for DR log {}: {}", dl.getId(), ex.toString()); }
					}
					return new AlarmDtos.DiagnosticResult(
							dl.getId(), dl.getSkillId(), s != null ? s.getName() : null,
							dl.getStatus(), drFindings, drOutputSchema, drCharts);
				})
				.toList();

		// Pipeline-native rendering: pull data_views (and charts/alerts) directly
		// from result_summary so the alarm UI can render the actual triggering
		// rows + diagnostic output without going through the legacy DR / skill
		// schema path. This is what the user sees when the alarm came from a
		// pipeline-mode patrol (block_alert + block_data_view), not the
		// legacy diagnostic_rules format.
		List<AlarmDtos.DataView> triggerDvs = extractDataViewsFromExecLog(execLog);
		// 2026-05-24: per-step data_views feed 深度診斷 tab when no auto_check
		// pipeline runs exist. Each step in the skill is conceptually a deep
		// diagnostic check; the auto_check fan-out is an OPTIONAL additional
		// layer. Without this fallback, skills with N internal checks but no
		// configured auto_check pipeline showed an empty 深度診斷 tab even
		// though each check returned a data_view.
		List<AlarmDtos.DataView> diagnosticDvs = extractPerStepDataViewsFromExecLog(execLog, a.getSkillId());
		List<Object> diagnosticCharts = List.of();
		Object diagnosticAlert = null;
		// auto_check writes to pb_pipeline_runs, not execution_logs — so when
		// diagLog is null but diagnostic_log_id is set, look it up on the
		// pipeline-run side. (V7 dropped the FK so the id can land in either
		// table.)
		if (a.getDiagnosticLogId() != null) {
			Optional<PipelineRunEntity> pr = safeFindRun(a.getDiagnosticLogId());
			if (pr.isPresent()) {
				PipelineRunEntity run = pr.get();
				JsonNode runNode = parseJsonNode(run.getNodeResults());
				if (runNode != null) {
					JsonNode rs = runNode.get("result_summary");
					if (rs != null && rs.isObject()) {
						diagnosticDvs = extractDataViews(rs.get("data_views"));
						JsonNode chartsNode = rs.get("charts");
						if (chartsNode != null && chartsNode.isArray()) {
							List<Object> list = new java.util.ArrayList<>();
							chartsNode.forEach(list::add);
							diagnosticCharts = list;
						}
						JsonNode alertsNode = rs.get("alerts");
						if (alertsNode != null && alertsNode.isArray() && alertsNode.size() > 0) {
							diagnosticAlert = alertsNode.get(0);
						}
					}
					// Surface as legacy diagnosticFindings too so old UI paths
					// still render *something* meaningful.
					if (diagFindings == null) diagFindings = runNode;
				}
			}
		}

		// P5+: an alarm may fire MULTIPLE auto_check pipelines. Runs are
		// pre-loaded in loadContext() (one bulk JSONB scan); we just look
		// up by alarm id here. alarm.diagnostic_log_id only points at one
		// run so UI used to lose the others.
		List<AlarmDtos.AutoCheckRun> autoCheckRuns = new java.util.ArrayList<>();
		List<PipelineRunEntity> allRuns = ctx.runsByAlarmId.getOrDefault(a.getId(), List.of());
		for (PipelineRunEntity r : allRuns) {
			JsonNode runNode = parseJsonNode(r.getNodeResults());
			List<AlarmDtos.DataView> dvs = List.of();
			List<Object> chartsList = List.of();
			Object alert = null;
			if (runNode != null) {
				JsonNode rs = runNode.get("result_summary");
				if (rs != null && rs.isObject()) {
					dvs = extractDataViews(rs.get("data_views"));
					JsonNode chartsNode = rs.get("charts");
					if (chartsNode != null && chartsNode.isArray()) {
						List<Object> list = new java.util.ArrayList<>();
						chartsNode.forEach(list::add);
						chartsList = list;
					}
					JsonNode alertsNode = rs.get("alerts");
					if (alertsNode != null && alertsNode.isArray() && alertsNode.size() > 0) {
						alert = alertsNode.get(0);
					}
				}
			}
			autoCheckRuns.add(new AlarmDtos.AutoCheckRun(
					r.getId(), r.getPipelineId(), ctx.pipelineNameById.get(r.getPipelineId()),
					r.getStatus(), dvs, chartsList, alert));
		}

		return new EnrichedFields(findings, outputSchema, diagFindings, diagOutputSchema,
				charts, diagnosticResults, triggerDvs, diagnosticDvs, diagnosticCharts, diagnosticAlert,
				autoCheckRuns);
	}

	private Optional<PipelineRunEntity> safeFindRun(Long id) {
		try {
			return pipelineRunRepo.findById(id);
		} catch (RuntimeException ex) {
			log.debug("alarm enrichment: pipeline_run lookup failed for id={}: {}", id, ex.getMessage());
			return Optional.empty();
		}
	}

	/** Confirm-step data_views = "what triggered the alarm" → 觸發原因 tab. */
	private List<AlarmDtos.DataView> extractDataViewsFromExecLog(ExecutionLogEntity log) {
		if (log == null) return List.of();
		JsonNode root = parseJsonNode(log.getLlmReadableData());
		if (root == null) return List.of();

		// 2026-05-24 fix: SkillAlarmEmitter.buildLlmReadableData writes the
		// findings map DIRECTLY as the JSON root (no top-level `findings`
		// wrapper). The previous `root.get("findings").get("step_details")`
		// path always returned null → trigger_data_views was always empty
		// for every alarm since the step_details restructure shipped.
		List<AlarmDtos.DataView> all = new java.util.ArrayList<>();
		JsonNode stepDetails = root.get("step_details");
		if (stepDetails != null) {
			JsonNode confirm = stepDetails.get("confirm");
			if (confirm != null) {
				all.addAll(extractDataViews(confirm.get("data_views")));
			}
		}

		// Legacy path (pre-2026-05-23): result_summary.data_views.
		// Kept for older execution_logs whose llm_readable_data was built
		// before the step_details restructure. Returns empty for new logs.
		if (all.isEmpty()) {
			JsonNode rs = root.get("result_summary");
			if (rs != null) {
				all.addAll(extractDataViews(rs.get("data_views")));
			}
		}
		return all;
	}

	/** Per-step data_views = "what each diagnostic check returned" → 深度診斷 tab
	 *  (when no auto_check pipeline ran). Each step's data_view is annotated
	 *  with the step's human-authored description (from skill_documents.steps[].text)
	 *  + the pass/fail result line, so the user sees both the "what" (check
	 *  description) and the "result" (status + note) per check, not just a
	 *  raw table.
	 *
	 *  <p>2026-05-24 splits + 2026-05-24 enrichment: was previously a flat
	 *  list of data_views without context — user feedback was that each
	 *  check should be presented "以檢查的項目裡的說明，結果來呈現"
	 *  (using the check item's description + result). confirm stays in
	 *  trigger_data_views; per_step here gets title/description overlays.
	 *
	 *  <p>{@code skillId} is the alarm's skill_id → maps to
	 *  {@code skill_documents.id} (NOT skill_definitions). steps JSON column
	 *  carries the per-step description text. */
	private List<AlarmDtos.DataView> extractPerStepDataViewsFromExecLog(ExecutionLogEntity log, Long skillId) {
		if (log == null) return List.of();
		JsonNode root = parseJsonNode(log.getLlmReadableData());
		if (root == null) return List.of();
		JsonNode stepDetails = root.get("step_details");
		if (stepDetails == null) return List.of();
		JsonNode perStep = stepDetails.get("per_step");
		if (perStep == null || !perStep.isObject()) return List.of();

		Map<String, StepMeta> stepMeta = loadStepMeta(skillId);

		// Collect per_step entries into a list first so we can sort by display
		// order (skill_documents.steps[].order) — JSON object iteration order
		// isn't guaranteed to match the user's declared sequence.
		record StepEntry(int order, AlarmDtos.DataView view) {}
		List<StepEntry> entries = new java.util.ArrayList<>();
		perStep.fields().forEachRemaining(entry -> {
			String stepId = entry.getKey();
			JsonNode step = entry.getValue();
			if (step == null) return;
			JsonNode statusNode = step.get("status");
			String status = statusNode == null ? "" : statusNode.asText("");
			JsonNode dvNode = step.get("data_views");
			boolean hasData = dvNode != null && dvNode.isArray() && dvNode.size() > 0;

			StepMeta meta = stepMeta.get(stepId);
			String desc = (meta != null && meta.text != null && !meta.text.isBlank())
					? meta.text : stepId;
			int displayOrder = meta != null ? meta.order : 9999;  // unknown order → end
			String note = step.has("note") ? step.get("note").asText("") : "";
			String value = step.has("value") ? step.get("value").asText("") : "";
			String resultLine = buildResultLine(status, value, note);

			// Surface every step the user defined in skill_documents.steps[],
			// regardless of pass/fail/empty-data — the user explicitly asked
			// for all 3 checks to be visible. Fail-with-no-data becomes a
			// result-only card so the user can see "[檢查 1] ... ✗ fail —
			// pipeline failed: null" instead of silently hiding it.
			if (hasData) {
				for (JsonNode dv : dvNode) {
					entries.add(new StepEntry(displayOrder,
							decorateDataView(dv, displayOrder, desc, resultLine)));
				}
			} else {
				entries.add(new StepEntry(displayOrder, new AlarmDtos.DataView(
						formatStepTitle(displayOrder, desc),
						resultLine,
						List.of(), List.of(), 0)));
			}
		});

		entries.sort(java.util.Comparator.comparingInt(StepEntry::order));
		return entries.stream().map(StepEntry::view).toList();
	}

	/** Metadata for a single step parsed from {@code skill_documents.steps}. */
	private record StepMeta(int order, String text) {}

	private Map<String, StepMeta> loadStepMeta(Long skillId) {
		if (skillId == null) return Map.of();
		try {
			Optional<SkillDocumentEntity> opt = skillDocRepo.findById(skillId);
			if (opt.isEmpty()) return Map.of();
			String stepsJson = opt.get().getSteps();
			if (stepsJson == null || stepsJson.isBlank()) return Map.of();
			JsonNode arr = parseJsonNode(stepsJson);
			if (arr == null || !arr.isArray()) return Map.of();
			Map<String, StepMeta> out = new HashMap<>();
			for (int i = 0; i < arr.size(); i++) {
				JsonNode node = arr.get(i);
				if (node == null) continue;
				String id = node.has("id") ? node.get("id").asText("") : "";
				if (id.isBlank()) continue;
				String text = node.has("text") ? node.get("text").asText("") : "";
				int order = node.has("order") && node.get("order").isNumber()
						? node.get("order").asInt() : i + 1;
				out.put(id, new StepMeta(order, text));
			}
			return out;
		} catch (RuntimeException ex) {
			log.debug("loadStepMeta({}) failed: {}", skillId, ex.toString());
			return Map.of();
		}
	}

	private static String formatStepTitle(int order, String desc) {
		return order > 0
				? String.format("[檢查 %d] %s", order, desc)
				: String.format("[檢查] %s", desc);
	}

	private static String buildResultLine(String status, String value, String note) {
		String icon = "pass".equalsIgnoreCase(status) ? "✓"
				: "fail".equalsIgnoreCase(status) ? "✗"
				: "•";
		StringBuilder sb = new StringBuilder();
		sb.append(icon).append(' ').append(status.isBlank() ? "ran" : status);
		if (note != null && !note.isBlank()) sb.append(" — ").append(note);
		else if (value != null && !value.isBlank()) sb.append(" — value: ").append(value);
		return sb.toString();
	}

	/** Build a DataView from the raw JSON node, overriding title with the
	 *  step description and description with the result line. Columns/rows/
	 *  total taken from the original node. */
	private AlarmDtos.DataView decorateDataView(JsonNode dv, int order, String desc, String resultLine) {
		List<String> cols = new java.util.ArrayList<>();
		JsonNode colsNode = dv.get("columns");
		if (colsNode != null && colsNode.isArray()) colsNode.forEach(c -> cols.add(c.asText()));
		List<Object> rows = new java.util.ArrayList<>();
		JsonNode rowsNode = dv.get("rows");
		if (rowsNode != null && rowsNode.isArray()) rowsNode.forEach(rows::add);
		Integer total = dv.has("total_rows") && dv.get("total_rows").isNumber()
				? dv.get("total_rows").asInt()
				: dv.has("total") && dv.get("total").isNumber()
						? dv.get("total").asInt()
						: rows.size();
		return new AlarmDtos.DataView(formatStepTitle(order, desc), resultLine, cols, rows, total);
	}

	private List<AlarmDtos.DataView> extractDataViews(JsonNode dvNode) {
		if (dvNode == null || !dvNode.isArray()) return List.of();
		List<AlarmDtos.DataView> out = new java.util.ArrayList<>();
		for (JsonNode dv : dvNode) {
			List<String> cols = new java.util.ArrayList<>();
			JsonNode colsNode = dv.get("columns");
			if (colsNode != null && colsNode.isArray()) {
				colsNode.forEach(c -> cols.add(c.asText()));
			}
			List<Object> rows = new java.util.ArrayList<>();
			JsonNode rowsNode = dv.get("rows");
			if (rowsNode != null && rowsNode.isArray()) {
				rowsNode.forEach(rows::add);
			}
			Integer total = dv.has("total_rows") && dv.get("total_rows").isNumber()
					? dv.get("total_rows").asInt() : rows.size();
			out.add(new AlarmDtos.DataView(
					textOrNull(dv.get("title")),
					textOrNull(dv.get("description")),
					cols, rows, total));
		}
		return out;
	}

	private static String textOrNull(JsonNode n) {
		return n == null || n.isNull() ? null : n.asText();
	}

	private JsonNode parseJsonNode(String raw) {
		if (raw == null || raw.isBlank()) return null;
		try { return mapper.readTree(raw); } catch (JsonProcessingException e) { return null; }
	}

	private Object parseJson(String raw) {
		if (raw == null || raw.isBlank()) return null;
		try {
			return mapper.readTree(raw);
		} catch (JsonProcessingException e) {
			log.debug("alarm enrichment: could not parse JSON ({}): {}", e.getMessage(),
					raw.substring(0, Math.min(80, raw.length())));
			return null;
		}
	}

	private static Long parseAlarmIdFromTrigger(String triggeredBy) {
		if (triggeredBy == null || !triggeredBy.startsWith("alarm:")) return null;
		try {
			String rest = triggeredBy.substring("alarm:".length());
			int colon = rest.indexOf(':');
			String idPart = colon >= 0 ? rest.substring(0, colon) : rest;
			return Long.parseLong(idPart.trim());
		} catch (NumberFormatException e) {
			return null;
		}
	}

	private record Ctx(Map<Long, ExecutionLogEntity> execs,
	                   Map<Long, SkillDefinitionEntity> skills,
	                   Map<Long, List<ExecutionLogEntity>> diagsByAlarmId,
	                   Map<Long, List<PipelineRunEntity>> runsByAlarmId,
	                   Map<Long, String> pipelineNameById) {}

	private record EnrichedFields(Object findings, Object outputSchema,
	                              Object diagnosticFindings, Object diagnosticOutputSchema,
	                              List<Object> charts,
	                              List<AlarmDtos.DiagnosticResult> diagnosticResults,
	                              List<AlarmDtos.DataView> triggerDataViews,
	                              List<AlarmDtos.DataView> diagnosticDataViews,
	                              List<Object> diagnosticCharts,
	                              Object diagnosticAlert,
	                              List<AlarmDtos.AutoCheckRun> autoCheckRuns) {}
}
