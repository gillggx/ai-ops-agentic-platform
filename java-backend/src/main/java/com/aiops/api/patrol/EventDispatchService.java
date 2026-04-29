package com.aiops.api.patrol;

import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.patrol.AutoPatrolEntity;
import com.aiops.api.domain.patrol.AutoPatrolRepository;
import com.aiops.api.domain.pipeline.PipelineAutoCheckTriggerEntity;
import com.aiops.api.domain.pipeline.PipelineAutoCheckTriggerRepository;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Phase C — fan-out subscribers when an event / alarm enters the system.
 *
 * <p>Two ingress points are routed here:
 * <ul>
 *   <li>{@link #dispatchGeneratedEvent} — called from
 *       InternalGeneratedEventController.create after writing a row to
 *       {@code generated_events}. Looks up active event-mode auto_patrols
 *       with matching event_type_id and fires each one.</li>
 *   <li>{@link #dispatchAlarm} — called from InternalAlarmController.create
 *       AND from AutoPatrolExecutor.writeAlarm after writing an alarm row.
 *       Looks up auto_check triggers whose event_type matches the alarm's
 *       trigger_event string and fires each diagnostic pipeline.</li>
 * </ul>
 *
 * <p>Both paths run async so they don't block the writing controller. Any
 * exception inside a dispatch is logged and swallowed — one bad subscriber
 * must not break the ingress write.
 */
@Slf4j
@Service
public class EventDispatchService {

	private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

	private final AutoPatrolRepository patrolRepo;
	private final PipelineAutoCheckTriggerRepository autoCheckRepo;
	private final AutoPatrolExecutor patrolExecutor;
	private final AutoCheckExecutor autoCheckExecutor;
	private final ObjectMapper objectMapper;

	public EventDispatchService(AutoPatrolRepository patrolRepo,
	                            PipelineAutoCheckTriggerRepository autoCheckRepo,
	                            AutoPatrolExecutor patrolExecutor,
	                            AutoCheckExecutor autoCheckExecutor,
	                            ObjectMapper objectMapper) {
		this.patrolRepo = patrolRepo;
		this.autoCheckRepo = autoCheckRepo;
		this.patrolExecutor = patrolExecutor;
		this.autoCheckExecutor = autoCheckExecutor;
		this.objectMapper = objectMapper;
	}

	/** Generated events → event-mode auto_patrols. */
	@Async
	public void dispatchGeneratedEvent(Long eventTypeId, String mappedParametersJson) {
		if (eventTypeId == null || eventTypeId == 0L) {
			log.debug("dispatchGeneratedEvent: skipping, event_type_id missing");
			return;
		}
		Map<String, Object> payload = parseJson(mappedParametersJson);
		List<AutoPatrolEntity> matched =
				patrolRepo.findByTriggerModeAndEventTypeIdAndIsActiveTrue("event", eventTypeId);
		if (matched.isEmpty()) {
			log.debug("dispatchGeneratedEvent: event_type_id={} no matching event-mode patrols", eventTypeId);
			return;
		}
		log.info("dispatchGeneratedEvent: event_type_id={} → {} patrol(s)", eventTypeId, matched.size());
		for (AutoPatrolEntity patrol : matched) {
			try {
				patrolExecutor.executePatrol(patrol.getId(), payload);
			} catch (Exception ex) {
				log.warn("dispatchGeneratedEvent: patrol id={} threw: {}",
						patrol.getId(), ex.getMessage(), ex);
			}
		}
	}

	/** Alarm write → auto_check pipelines. */
	@Async
	public void dispatchAlarm(AlarmEntity alarm) {
		if (alarm == null) return;
		String eventType = alarm.getTriggerEvent();
		if (eventType == null || eventType.isBlank()) {
			log.debug("dispatchAlarm: skipping alarm id={}, trigger_event empty", alarm.getId());
			return;
		}
		List<PipelineAutoCheckTriggerEntity> matched = autoCheckRepo.findByEventType(eventType);
		if (matched.isEmpty()) {
			log.debug("dispatchAlarm: alarm id={} trigger_event='{}' no matching auto_check pipelines",
					alarm.getId(), eventType);
			return;
		}
		Map<String, Object> alarmPayload = alarmToPayload(alarm);
		int firedCount = 0;
		for (PipelineAutoCheckTriggerEntity trig : matched) {
			Long pipelineId = trig.getPipelineId();
			if (pipelineId == null) continue;
			// Phase D — per-trigger attribute filter. NULL = no filter
			// (legacy + back-compat). Filter mismatch → skip silently
			// (debug log only); fail-open on parse error.
			if (!matchesFilter(trig.getMatchFilter(), alarmPayload, alarm.getId())) {
				log.debug("dispatchAlarm: alarm id={} skipped pipeline={} (filter mismatch)",
						alarm.getId(), pipelineId);
				continue;
			}
			firedCount++;
			try {
				autoCheckExecutor.executeAutoCheck(pipelineId, alarmPayload, alarm.getId());
			} catch (Exception ex) {
				log.warn("dispatchAlarm: pipeline id={} threw: {}",
						pipelineId, ex.getMessage(), ex);
			}
		}
		log.info("dispatchAlarm: alarm id={} trigger_event='{}' → {}/{} pipeline(s) fired (after filter)",
				alarm.getId(), eventType, firedCount, matched.size());
	}

	/** Whitelist of alarm-payload keys a match_filter clause may use. Anything
	 *  outside this set is logged + ignored — we don't want a typo in a
	 *  filter to silently fall through and drop everything. */
	private static final java.util.Set<String> ALLOWED_FILTER_KEYS = java.util.Set.of(
			"equipment_id", "tool_id", "lot_id", "step", "severity",
			"event_time", "title", "summary", "trigger_event"
	);

	/** Evaluate a match_filter JSON against the alarm payload.
	 *
	 *  <p>Rules:
	 *  <ul>
	 *    <li>NULL / blank → match (no filter).</li>
	 *    <li>Each clause: {@code key=value} or {@code key=[v1,v2,...]} (OR).</li>
	 *    <li>All clauses must pass (AND).</li>
	 *    <li>Unknown key → log warn + skip clause (other clauses still apply).</li>
	 *    <li>Parse failure → log warn + return true (fail-open) so a corrupt
	 *        filter doesn't drop every pipeline silently.</li>
	 *  </ul>
	 */
	@SuppressWarnings("unchecked")
	boolean matchesFilter(String filterJson, Map<String, Object> payload, Long alarmId) {
		if (filterJson == null || filterJson.isBlank()) return true;
		Map<String, Object> filter;
		try {
			filter = objectMapper.readValue(filterJson, MAP_TYPE);
		} catch (Exception ex) {
			log.warn("matchesFilter: alarm id={} filter parse failed ({}); fail-open",
					alarmId, ex.getMessage());
			return true;
		}
		for (Map.Entry<String, Object> clause : filter.entrySet()) {
			String key = clause.getKey();
			if (!ALLOWED_FILTER_KEYS.contains(key)) {
				log.warn("matchesFilter: alarm id={} filter key '{}' not in whitelist; skip clause",
						alarmId, key);
				continue;
			}
			Object actual = payload.get(key);
			Object expected = clause.getValue();
			if (expected instanceof List<?> options) {
				boolean any = false;
				for (Object opt : options) {
					if (sameValue(opt, actual)) { any = true; break; }
				}
				if (!any) return false;
			} else {
				if (!sameValue(expected, actual)) return false;
			}
		}
		return true;
	}

	/** Loose equality: null == null, otherwise compare String forms. */
	private static boolean sameValue(Object a, Object b) {
		if (a == null && b == null) return true;
		if (a == null || b == null) return false;
		return String.valueOf(a).equals(String.valueOf(b));
	}

	private Map<String, Object> parseJson(String raw) {
		if (raw == null || raw.isBlank()) return Map.of();
		try {
			return objectMapper.readValue(raw, MAP_TYPE);
		} catch (Exception ex) {
			log.warn("dispatch: payload JSON parse failed ({}): {}", ex.getMessage(),
					raw.substring(0, Math.min(raw.length(), 200)));
			return Map.of();
		}
	}

	private Map<String, Object> alarmToPayload(AlarmEntity alarm) {
		Map<String, Object> p = new HashMap<>();
		// Keys mirror alarm column names so a match_filter clause `{severity:
		// ["HIGH"]}` finds the value at p.get("severity"), AND so an
		// auto_check pipeline declaring input `severity` (or equipment_id,
		// step, etc.) gets its value injected by name.
		p.put("equipment_id", alarm.getEquipmentId());
		p.put("tool_id", alarm.getEquipmentId());  // mirror so either name works
		p.put("lot_id", alarm.getLotId());
		if (alarm.getStep() != null) p.put("step", alarm.getStep());
		if (alarm.getEventTime() != null) p.put("event_time", alarm.getEventTime().toString());
		p.put("severity", alarm.getSeverity());
		p.put("title", alarm.getTitle());
		if (alarm.getSummary() != null) p.put("summary", alarm.getSummary());
		p.put("trigger_event", alarm.getTriggerEvent());
		// Identity for traceability — diagnostic pipeline can echo this back
		// in its run row's node_results.
		p.put("alarm_id", alarm.getId());
		return p;
	}
}
