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
}
