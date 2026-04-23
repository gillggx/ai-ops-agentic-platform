package com.aiops.api.api.alarm;

import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.skill.ExecutionLogEntity;
import com.aiops.api.domain.skill.ExecutionLogRepository;
import com.aiops.api.domain.skill.SkillDefinitionEntity;
import com.aiops.api.domain.skill.SkillDefinitionRepository;
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
	private final ObjectMapper mapper;
	private final ChartMiddleware chartMiddleware;

	public AlarmEnrichmentService(ExecutionLogRepository execLogRepo,
	                              SkillDefinitionRepository skillRepo,
	                              ObjectMapper mapper,
	                              ChartMiddleware chartMiddleware) {
		this.execLogRepo = execLogRepo;
		this.skillRepo = skillRepo;
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
		for (AlarmEntity a : alarms) {
			if (a.getExecutionLogId() != null) execIds.add(a.getExecutionLogId());
			if (a.getDiagnosticLogId() != null) execIds.add(a.getDiagnosticLogId());
			if (a.getSkillId() != null) skillIds.add(a.getSkillId());
			triggerKeys.add("alarm:" + a.getId());
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

		return new Ctx(execsById, skillsById, diagsByAlarmId);
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
				f.diagnosticResults);
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
				f.diagnosticResults);
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
						catch (Exception ex) { log.warn("chart-middleware failed for DR log {}: {}", dl.getId(), ex.toString()); }
					}
					return new AlarmDtos.DiagnosticResult(
							dl.getId(), dl.getSkillId(), s != null ? s.getName() : null,
							dl.getStatus(), drFindings, drOutputSchema, drCharts);
				})
				.toList();

		return new EnrichedFields(findings, outputSchema, diagFindings, diagOutputSchema, charts, diagnosticResults);
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
	                   Map<Long, List<ExecutionLogEntity>> diagsByAlarmId) {}

	private record EnrichedFields(Object findings, Object outputSchema,
	                              Object diagnosticFindings, Object diagnosticOutputSchema,
	                              List<Object> charts,
	                              List<AlarmDtos.DiagnosticResult> diagnosticResults) {}
}
