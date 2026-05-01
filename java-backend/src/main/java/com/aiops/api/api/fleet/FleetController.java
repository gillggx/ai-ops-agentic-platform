package com.aiops.api.api.fleet;

import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Endpoints for the redesigned Dashboard fleet overview (Phase 1).
 * SPEC: docs/SPEC_dashboard_redesign_v1_phase1.md §2.1.
 *
 * <p>Note: AI hero narrative streaming reuses the existing
 * {@code /api/v1/briefing} SSE infrastructure with a new {@code scope=fleet}
 * value (see {@code python_ai_sidecar/routers/briefing.py}). No endpoint
 * is needed here for that.
 */
@RestController
@RequestMapping("/api/v1/fleet")
@PreAuthorize(Authorities.ANY_ROLE)
public class FleetController {

	private final FleetService service;

	public FleetController(FleetService service) {
		this.service = service;
	}

	@GetMapping("/equipment")
	public ApiResponse<FleetDtos.EquipmentListResponse> equipment(
			@RequestParam(name = "since_hours", defaultValue = "24") int sinceHours) {
		return ApiResponse.ok(service.listEquipment(sinceHours));
	}

	@GetMapping("/concerns")
	public ApiResponse<FleetDtos.ConcernListResponse> concerns(
			@RequestParam(name = "since_hours", defaultValue = "24") int sinceHours) {
		return ApiResponse.ok(service.computeConcerns(sinceHours));
	}

	@GetMapping("/stats")
	public ApiResponse<FleetDtos.FleetStats> stats(
			@RequestParam(name = "since_hours", defaultValue = "24") int sinceHours) {
		return ApiResponse.ok(service.computeStats(sinceHours));
	}

	// ── Phase 2 — per-equipment detail ─────────────────────────

	@GetMapping("/equipment/{id}/timeline")
	public ApiResponse<FleetDtos.TimelineResponse> timeline(
			@org.springframework.web.bind.annotation.PathVariable String id,
			@RequestParam(name = "since_hours", defaultValue = "24") int sinceHours) {
		return ApiResponse.ok(service.computeTimeline(id, sinceHours));
	}

	@GetMapping("/equipment/{id}/modules")
	public ApiResponse<FleetDtos.ModulesResponse> modules(
			@org.springframework.web.bind.annotation.PathVariable String id,
			@RequestParam(name = "since_hours", defaultValue = "24") int sinceHours) {
		return ApiResponse.ok(service.computeModules(id, sinceHours));
	}

	@GetMapping("/equipment/{id}/spc-trace")
	public ApiResponse<FleetDtos.SpcTraceResponse> spcTrace(
			@org.springframework.web.bind.annotation.PathVariable String id,
			@RequestParam(defaultValue = "100") int limit) {
		return ApiResponse.ok(service.computeSpcTrace(id, limit));
	}
}
