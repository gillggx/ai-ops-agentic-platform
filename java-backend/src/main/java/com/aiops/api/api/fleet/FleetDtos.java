package com.aiops.api.api.fleet;

import java.time.OffsetDateTime;
import java.util.List;

/** DTOs for the Dashboard Fleet Overview redesign (Phase 1).
 *  Field shape matches docs/SPEC_dashboard_redesign_v1_phase1.md §2.1.
 *
 *  All counts are scoped to {@code since_hours} (default 24h) on the
 *  controller side; the service receives a resolved OffsetDateTime. */
public final class FleetDtos {

	private FleetDtos() {}

	/** One row in the ranked tool list. */
	public record Equipment(
			String id,
			String name,
			String health,        // "crit" | "warn" | "healthy"
			int score,            // 0..100
			double ooc,           // %
			int oocCount,
			int alarms,
			int fdc,
			int lots24h,
			String trend,         // "up" | "down" | "flat"
			String note,
			List<Integer> hourly  // 24 entries; OOC alarm count per hour bucket
	) {}

	public record EquipmentListResponse(
			String since,
			OffsetDateTime asOf,
			int total,
			List<Equipment> equipment
	) {}

	/** AI Briefing rule-engine output (max 3 entries). */
	public record Concern(
			String id,
			String ruleId,
			String severity,      // "crit" | "warn"
			double confidence,    // 0..1
			String title,
			String detail,
			List<String> tools,
			List<String> steps,
			int evidence,
			List<String> actions
	) {}

	public record ConcernListResponse(
			String since,
			OffsetDateTime asOf,
			List<Concern> concerns
	) {}

	/** Fleet-wide aggregates for the hero sidebar. */
	public record FleetStats(
			double fleetOocRate,
			int oocEvents,
			int totalEvents,
			int fdcAlerts,
			int openAlarms,
			int affectedLots,
			int critCount,
			int warnCount,
			OffsetDateTime asOf
	) {}

	// ── Phase 2: per-equipment detail ──────────────────────────

	/** One event on the multi-lane health timeline.
	 *  {@code lane} maps to the y-axis row: ooc / apc / fdc / ec / recipe / lot. */
	public record TimelineEvent(
			OffsetDateTime t,
			String lane,
			String severity,    // "crit" | "warn" | "info" | "ok"
			String label,
			String detail
	) {}

	public record TimelineResponse(
			String equipmentId,
			OffsetDateTime since,
			OffsetDateTime asOf,
			List<TimelineEvent> events
	) {}

	/** One status card in the 5-light module row. */
	public record ModuleStatus(
			String key,         // "SPC" | "APC" | "FDC" | "DC" | "EC"
			String state,       // "crit" | "warn" | "ok"
			String value,       // big number / phrase
			String sub          // 1-line caption
	) {}

	public record ModulesResponse(
			String equipmentId,
			OffsetDateTime asOf,
			List<ModuleStatus> modules
	) {}

	/** Single SPC chart trace + control limits. */
	public record SpcTrace(
			String chart,
			List<Double> values,
			List<OffsetDateTime> times,
			double ucl,
			double lcl,
			double target
	) {}

	public record SpcTraceResponse(
			String equipmentId,
			OffsetDateTime asOf,
			List<SpcTrace> charts
	) {}
}
