package com.aiops.api.api.patrol;

import com.aiops.api.common.JsonUtils;
import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.domain.event.GeneratedEventRepository;
import com.aiops.api.domain.skill.SkillDocumentEntity;
import com.aiops.api.domain.skill.SkillDocumentRepository;
import com.aiops.api.domain.skill.SkillRunEntity;
import com.aiops.api.domain.skill.SkillRunRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Patrol Activity service — assembles the funnel summary + per-run items
 * for {@link PatrolActivityController}.
 *
 * <p>Implementation notes:
 * <ul>
 *   <li>Items are anchored on {@code skill_runs} — the canonical "auto-check
 *       happened here" record. We then bulk-load the skills (for stage /
 *       slug / title) and the alarms (for the green-light link), keeping the
 *       N+1 footprint to three queries total.</li>
 *   <li>Event provenance (event_type / equipment_id / lot_id / step_id) is
 *       read from {@code skill_run.trigger_payload} rather than from a real
 *       JOIN against {@code generated_events} — there is no FK on the wire,
 *       only payload similarity, and reconstructing it post-hoc would mean
 *       fuzzy time-window matching that the UI is not asking for.</li>
 *   <li>Funnel counts are independent simple {@code COUNT(*)} queries — no
 *       JOIN, no GROUP BY, sub-second on the indexes we have.</li>
 * </ul>
 */
@Service
public class PatrolActivityService {

	private final SkillRunRepository runRepo;
	private final SkillDocumentRepository skillRepo;
	private final AlarmRepository alarmRepo;
	private final GeneratedEventRepository eventRepo;
	private final ObjectMapper mapper;

	public PatrolActivityService(SkillRunRepository runRepo,
	                             SkillDocumentRepository skillRepo,
	                             AlarmRepository alarmRepo,
	                             GeneratedEventRepository eventRepo,
	                             ObjectMapper mapper) {
		this.runRepo = runRepo;
		this.skillRepo = skillRepo;
		this.alarmRepo = alarmRepo;
		this.eventRepo = eventRepo;
		this.mapper = mapper;
	}

	@Transactional(readOnly = true)
	public PatrolActivityResponse queryActivity(Query q) {
		List<SkillRunEntity> runs = runRepo.findActivity(
				q.since(), q.until(), q.skillId(), q.cursor(), q.limit() + 1);

		boolean hasMore = runs.size() > q.limit();
		if (hasMore) runs = runs.subList(0, q.limit());

		// Bulk-load skills + alarms for the page in one shot each.
		Set<Long> skillIds = new HashSet<>();
		Set<Long> runIds = new HashSet<>();
		for (SkillRunEntity r : runs) {
			skillIds.add(r.getSkillId());
			runIds.add(r.getId());
		}
		Map<Long, SkillDocumentEntity> skillsById = new HashMap<>();
		if (!skillIds.isEmpty()) {
			for (SkillDocumentEntity s : skillRepo.findAllById(skillIds)) {
				skillsById.put(s.getId(), s);
			}
		}
		Map<Long, AlarmEntity> alarmsByRunId = new HashMap<>();
		if (!runIds.isEmpty()) {
			for (AlarmEntity a : alarmRepo.findBySkillRunIdIn(runIds)) {
				alarmsByRunId.put(a.getSkillRunId(), a);
			}
		}

		// Build items with stage + event-type + outcome filters applied AFTER
		// skill enrichment. Stage + event_type filtering can't go into the
		// JPQL: stage triggers Hibernate's bytea-on-null type quirk in
		// LOWER(:p), and event_type lives in trigger_config JSON.
		List<Item> items = new ArrayList<>(runs.size());
		for (SkillRunEntity r : runs) {
			SkillDocumentEntity skill = skillsById.get(r.getSkillId());
			if (q.skillStage() != null && !q.skillStage().isBlank()) {
				String runStage = skill != null ? skill.getStage() : null;
				if (runStage == null || !q.skillStage().equalsIgnoreCase(runStage)) continue;
			}
			String triggerEventName = extractTriggerEventName(skill);
			if (q.eventType() != null && !q.eventType().isBlank()
					&& !q.eventType().equalsIgnoreCase(triggerEventName)) {
				continue;
			}
			Item item = buildItem(r, skill, triggerEventName, alarmsByRunId.get(r.getId()));
			if (passesOutcomeFilter(item, q.outcome())) {
				items.add(item);
			}
		}

		Long nextCursor = hasMore && !runs.isEmpty()
				? runs.get(runs.size() - 1).getId()
				: null;

		Funnel funnel = computeFunnel(q.since(), q.until());
		return new PatrolActivityResponse(funnel, items, nextCursor);
	}

	// ─── Funnel computation ─────────────────────────────────────────────

	private Funnel computeFunnel(OffsetDateTime since, OffsetDateTime until) {
		long events = eventRepo.countByCreatedAtBetween(since, until);
		long runs = runRepo.countByTriggeredAtBetween(since, until);
		long stepPassed = runRepo.countByTriggeredAtBetweenAndStepPassed(since, until);
		long alarms = alarmRepo.countByCreatedAtBetween(since, until);
		long dedupSuppressed = runRepo.countByTriggeredAtBetweenAndAlarmSkippedReason(since, until, "dedup");
		return new Funnel(events, runs, stepPassed, alarms, dedupSuppressed);
	}

	// ─── Item assembly ──────────────────────────────────────────────────

	private Item buildItem(SkillRunEntity r,
	                       SkillDocumentEntity skill,
	                       String triggerEventName,
	                       AlarmEntity alarm) {
		Map<String, Object> payload = JsonUtils.parseObject(mapper, r.getTriggerPayload());
		List<Map<String, Object>> steps = parseStepResults(r.getStepResults());

		int stepsTotal = steps.size();
		int stepsPassed = (int) steps.stream()
				.filter(s -> "pass".equalsIgnoreCase(String.valueOf(s.get("status"))))
				.count();

		String slug = skill != null ? skill.getSlug() : null;
		String title = skill != null ? skill.getTitle() : null;
		String stage = skill != null ? skill.getStage() : null;

		Long alarmId = alarm != null ? alarm.getId() : null;

		return new Item(
				r.getId(),
				r.getSkillId(),
				slug,
				title,
				stage,
				r.getTriggeredAt(),
				r.getTriggeredBy(),
				r.getDurationMs() != null ? r.getDurationMs().longValue() : null,
				r.getStatus(),
				stepsTotal,
				stepsPassed,
				triggerEventName,
				stringField(payload, "event_time"),
				stringField(payload, "equipment_id", "tool_id"),
				stringField(payload, "lot_id", "lotID"),
				stringField(payload, "step_id", "step"),
				alarmId,
				r.getAlarmSkippedReason()
		);
	}

	@SuppressWarnings("unchecked")
	private List<Map<String, Object>> parseStepResults(String json) {
		if (json == null || json.isBlank() || "[]".equals(json)) return List.of();
		Map<String, Object> root = JsonUtils.parseObject(mapper, json);
		if (root.containsKey("steps") && root.get("steps") instanceof List<?> list) {
			return (List<Map<String, Object>>) list;
		}
		// Legacy format: bare list, not the {steps, confirm} wrapper.
		List<Map<String, Object>> flat = JsonUtils.parseListOfObjects(mapper, json);
		return flat;
	}

	private boolean passesOutcomeFilter(Item item, String outcome) {
		if (outcome == null || outcome.isBlank() || "any".equalsIgnoreCase(outcome)) return true;
		switch (outcome.toLowerCase()) {
			case "alarm_emitted":
				return item.alarmId() != null;
			case "step_passed":
				return item.stepsPassed() > 0 && item.alarmId() == null;
			case "no_op":
				return item.stepsTotal() == 0;
			case "error":
				return "failed".equalsIgnoreCase(item.status());
			default:
				return true;
		}
	}

	private String extractTriggerEventName(SkillDocumentEntity skill) {
		if (skill == null) return null;
		Map<String, Object> cfg = JsonUtils.parseObject(mapper, skill.getTriggerConfig());
		Object ev = cfg.get("event");
		return ev != null ? String.valueOf(ev) : null;
	}

	private String stringField(Map<String, Object> payload, String... keys) {
		if (payload == null || payload.isEmpty()) return null;
		for (String k : keys) {
			Object v = payload.get(k);
			if (v != null && !String.valueOf(v).isBlank()) return String.valueOf(v);
		}
		return null;
	}

	// ─── Request / response DTOs ────────────────────────────────────────

	public record Query(
			OffsetDateTime since, OffsetDateTime until,
			String eventType, Long skillId, String skillStage, String outcome,
			int limit, Long cursor
	) {}

	public record PatrolActivityResponse(Funnel funnel, List<Item> items, Long nextCursor) {}

	public record Funnel(long events, long skillRuns, long stepPassed,
	                     long alarms, long dedupSuppressed) {}

	public record Item(
			Long skillRunId, Long skillId, String skillSlug, String skillTitle, String skillStage,
			OffsetDateTime triggeredAt, String triggeredBy, Long durationMs, String status,
			int stepsTotal, int stepsPassed,
			String eventType, String eventTime,
			String equipmentId, String lotId, String stepId,
			Long alarmId, String alarmSkippedReason
	) {}
}
