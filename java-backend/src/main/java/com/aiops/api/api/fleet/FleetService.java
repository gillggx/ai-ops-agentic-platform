package com.aiops.api.api.fleet;

import org.springframework.stereotype.Service;

/**
 * Fleet API façade.
 *
 * <p>After Phase 12 Java OOP refactor (2026-05-23) this is a thin
 * delegating façade so the existing {@link FleetController} surface
 * stays unchanged while the 959-LoC god service is split into three
 * cohesive @Service beans:
 *
 * <ul>
 *   <li>{@link FleetRosterService} — fleet-wide list / Top-3 concerns /
 *       fleet stats (SPEC §2.1.A–C)</li>
 *   <li>{@link FleetEquipmentDetailService} — per-equipment timeline /
 *       module status / SPC trace / lot lineage (Phase 2–3)</li>
 *   <li>{@link FleetSimulatorClient} — shared simulator HTTP infrastructure
 *       used by both</li>
 * </ul>
 *
 * <p>Methods here are 1-line delegates. New endpoints should add their
 * implementation to one of the focused services and add a delegate here
 * (so the controller's blast radius stays bounded).
 */
@Service
public class FleetService {

	private final FleetRosterService roster;
	private final FleetEquipmentDetailService detail;

	public FleetService(FleetRosterService roster, FleetEquipmentDetailService detail) {
		this.roster = roster;
		this.detail = detail;
	}

	// ── Fleet-wide ─────────────────────────────────────────────────────────

	public FleetDtos.EquipmentListResponse listEquipment(int sinceHours) {
		return roster.listEquipment(sinceHours);
	}

	public FleetDtos.ConcernListResponse computeConcerns(int sinceHours) {
		return roster.computeConcerns(sinceHours);
	}

	public FleetDtos.FleetStats computeStats(int sinceHours) {
		return roster.computeStats(sinceHours);
	}

	// ── Per-equipment ──────────────────────────────────────────────────────

	public FleetDtos.TimelineResponse computeTimeline(String equipmentId, int sinceHours) {
		return detail.computeTimeline(equipmentId, sinceHours);
	}

	public FleetDtos.ModulesResponse computeModules(String equipmentId, int sinceHours) {
		return detail.computeModules(equipmentId, sinceHours);
	}

	public FleetDtos.SpcTraceResponse computeSpcTrace(String equipmentId, int limit) {
		return detail.computeSpcTrace(equipmentId, limit);
	}

	public FleetDtos.LineageResponse computeLineage(String equipmentId, String lotIdParam) {
		return detail.computeLineage(equipmentId, lotIdParam);
	}
}
