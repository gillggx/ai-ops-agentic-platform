package com.aiops.api.api.patrol;

import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;

/**
 * Patrol Activity — operational view of "what happened between simulator
 * events and the alarms that landed in Alarm Center".
 *
 * <p>Before this controller existed, the Alarm Center showed only the tail of
 * the funnel: alarm rows that successfully emitted. Oncall engineers had no
 * UI to answer "did my skill run? did the step_check pass? if so, why no
 * alarm?". This endpoint surfaces every per-skill execution including the
 * 5 reasons {@code SkillAlarmEmitter} can suppress an alarm
 * (see {@code skill_runs.alarm_skipped_reason}).
 *
 * <p>Response shape (one row per skill_run):
 * <pre>
 *   {
 *     funnel: { events, skill_runs, step_passed, alarms, dedup_suppressed },
 *     items: [{
 *        skill_run_id, skill_id, skill_slug, skill_title, skill_stage,
 *        triggered_at, triggered_by, duration_ms, status,
 *        steps_total, steps_passed,
 *        event_type, event_time, equipment_id, lot_id, step_id,
 *        alarm_id, alarm_skipped_reason,
 *     }, ...],
 *     next_cursor: null|Long
 *   }
 * </pre>
 *
 * <p>Items are joined on the Java side (no SQL JOIN) because
 * {@code generated_events ↔ skill_runs} have no FK — the link is reconstructed
 * via payload fields stored on both. Time-bounded queries + indexes on
 * {@code skill_runs.triggered_at} keep the page query under 200ms at typical
 * traffic (24h ≈ 8000 skill_runs).
 */
@RestController
@RequestMapping("/api/v1/patrol-activity")
public class PatrolActivityController {

	private final PatrolActivityService service;

	public PatrolActivityController(PatrolActivityService service) {
		this.service = service;
	}

	@GetMapping
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<PatrolActivityService.PatrolActivityResponse> list(
			@RequestParam(required = false) String since,
			@RequestParam(required = false) String until,
			@RequestParam(required = false) String eventType,
			@RequestParam(required = false) Long skillId,
			@RequestParam(required = false) String skillStage,
			@RequestParam(required = false) String outcome,
			@RequestParam(defaultValue = "100") int limit,
			@RequestParam(required = false) Long cursor) {
		OffsetDateTime sinceTs = parseOrDefault(since, OffsetDateTime.now().minusHours(1));
		OffsetDateTime untilTs = parseOrDefault(until, OffsetDateTime.now());
		int safeLimit = Math.min(Math.max(limit, 1), 500);
		PatrolActivityService.Query q = new PatrolActivityService.Query(
				sinceTs, untilTs, eventType, skillId, skillStage, outcome, safeLimit, cursor);
		return ApiResponse.ok(service.queryActivity(q));
	}

	private static OffsetDateTime parseOrDefault(String raw, OffsetDateTime fallback) {
		if (raw == null || raw.isBlank()) return fallback;
		try {
			return OffsetDateTime.parse(raw);
		} catch (DateTimeParseException e) {
			return fallback;
		}
	}
}
