/**
 * Fleet Dashboard HTTP layer + business services.
 *
 * <p>Layering (Phase 12 OOP refactor 2026-05-23):
 * <ul>
 *   <li>{@link com.aiops.api.api.fleet.FleetController} — thin HTTP for
 *       the 7 dashboard endpoints (equipment / concerns / stats / per-
 *       equipment timeline + modules + spc-trace + lineage).</li>
 *   <li>{@link com.aiops.api.api.fleet.FleetService} — façade; delegates
 *       to the focused sub-services. Methods are 1-line passthroughs so
 *       the controller surface stays unchanged.</li>
 *   <li>{@link com.aiops.api.api.fleet.FleetRosterService} — SPEC §2.1.A–C:
 *       fleet-wide equipment list + Top-3 Concerns rule engine
 *       (R1 critical / R2 rising trend / R3 cross-step cluster) + fleet
 *       stats. Owns the health-score compute.</li>
 *   <li>{@link com.aiops.api.api.fleet.FleetEquipmentDetailService} —
 *       Phase 2/3: per-equipment timeline / module status (SPC/APC/FDC/
 *       DC/EC) / SPC trace / lot lineage. Reuses RosterService for
 *       lineage's TOOL node so dashboard visual continuity is preserved.</li>
 *   <li>{@link com.aiops.api.api.fleet.FleetSimulatorClient} — shared
 *       {@code WebClient} infrastructure (4 fetch* methods); fail-open
 *       to empty list/map so Dashboard degrades gracefully when the
 *       simulator is unreachable.</li>
 *   <li>{@link com.aiops.api.api.fleet.FleetDtos} — HTTP response shapes
 *       (Equipment / Concern / Stats / TimelineEvent / ModuleStatus /
 *       SpcTrace / LineageNode / etc.).</li>
 * </ul>
 *
 * <p>Read-only — no DB writes anywhere in this package. Alarms come from
 * {@code AlarmRepository}; process events come from the simulator.
 */
package com.aiops.api.api.fleet;
