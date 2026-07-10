package com.aiops.api.api.internal;

import com.aiops.api.api.alarm.AlarmClusterService;
import com.aiops.api.api.alarm.AlarmDtos;
import com.aiops.api.api.alarm.AlarmEnrichmentService;
import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.scheduler.SchedulerHttpClient;
import jakarta.validation.constraints.NotNull;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.util.Map;

/** Patrol / pipeline runs publishing alarms back from the sidecar (POST), plus
 *  read endpoints the internal Coordinator agent uses when IT admin grants it
 *  the alarm capabilities 對內 (Phase 6). */
@RestController
@RequestMapping("/internal/alarms")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalAlarmController {

	private final AlarmRepository repository;
	private final SchedulerHttpClient scheduler;
	private final AlarmClusterService clusterService;
	private final AlarmEnrichmentService enrichment;

	public InternalAlarmController(AlarmRepository repository,
	                                SchedulerHttpClient scheduler,
	                                AlarmClusterService clusterService,
	                                AlarmEnrichmentService enrichment) {
		this.repository = repository;
		this.scheduler = scheduler;
		this.clusterService = clusterService;
		this.enrichment = enrichment;
	}

	/** Fab-wide 告警現況 — clusters + KPIs (Coordinator's list_alarms). */
	@GetMapping("/situation")
	public ApiResponse<Map<String, Object>> situation(
			@RequestParam(name = "since_hours", defaultValue = "24") int sinceHours) {
		return ApiResponse.ok(Map.of(
				"clusters", clusterService.computeClusters(sinceHours, null),
				"kpis", clusterService.computeKpis(sinceHours)));
	}

	/** Filtered alarm HISTORY incl. handling state (Coordinator's query_alarms,
	 *  2026-07-10). Unlike /situation (現在的戰況), this answers「EQP-07 過去
	 *  N 天有哪些告警、處理到哪了」— per-alarm status / acked-by / disposition. */
	@GetMapping("/query")
	public ApiResponse<java.util.List<Map<String, Object>>> query(
			@RequestParam(name = "equipment_id", required = false) String equipmentId,
			@RequestParam(name = "since_hours", defaultValue = "168") int sinceHours,
			@RequestParam(required = false) String status,
			@RequestParam(required = false) String severity,
			@RequestParam(defaultValue = "50") int limit) {
		int safeLimit = Math.min(Math.max(limit, 1), 200);
		OffsetDateTime since = OffsetDateTime.now(java.time.ZoneOffset.UTC)
				.minusHours(Math.min(Math.max(sinceHours, 1), 24 * 90));
		java.util.List<Map<String, Object>> out = repository.findAll().stream()
				.filter(a -> a.getCreatedAt() != null && a.getCreatedAt().isAfter(since))
				.filter(a -> equipmentId == null || equipmentId.isBlank()
						|| equipmentId.equalsIgnoreCase(a.getEquipmentId()))
				.filter(a -> status == null || status.isBlank()
						|| status.equalsIgnoreCase(a.getStatus()))
				.filter(a -> severity == null || severity.isBlank()
						|| severity.equalsIgnoreCase(a.getSeverity()))
				.sorted(java.util.Comparator.comparing(AlarmEntity::getCreatedAt).reversed())
				.limit(safeLimit)
				.map(a -> {
					Map<String, Object> m = new java.util.LinkedHashMap<>();
					m.put("id", a.getId());
					m.put("title", a.getTitle());
					m.put("equipment_id", a.getEquipmentId());
					m.put("severity", a.getSeverity());
					m.put("status", a.getStatus());
					m.put("created_at", a.getCreatedAt());
					m.put("acknowledged_by", a.getAcknowledgedBy());
					m.put("acknowledged_at", a.getAcknowledgedAt());
					m.put("disposition", a.getDisposition());
					m.put("disposition_reason", a.getDispositionReason());
					m.put("resolved_at", a.getResolvedAt());
					return m;
				})
				.toList();
		return ApiResponse.ok(out);
	}

	/** Handling statistics (Coordinator's get_alarm_stats, 2026-07-10):
	 *  per-equipment counts + status/severity breakdown + ack rate. */
	@GetMapping("/stats")
	public ApiResponse<Map<String, Object>> stats(
			@RequestParam(name = "since_hours", defaultValue = "168") int sinceHours) {
		OffsetDateTime since = OffsetDateTime.now(java.time.ZoneOffset.UTC)
				.minusHours(Math.min(Math.max(sinceHours, 1), 24 * 90));
		var rows = repository.findAll().stream()
				.filter(a -> a.getCreatedAt() != null && a.getCreatedAt().isAfter(since))
				.toList();
		Map<String, Long> byEquipment = new java.util.TreeMap<>();
		Map<String, Long> byStatus = new java.util.TreeMap<>();
		Map<String, Long> bySeverity = new java.util.TreeMap<>();
		long acked = 0, disposed = 0;
		for (AlarmEntity a : rows) {
			byEquipment.merge(a.getEquipmentId() == null ? "(unknown)" : a.getEquipmentId(), 1L, Long::sum);
			byStatus.merge(a.getStatus() == null ? "open" : a.getStatus(), 1L, Long::sum);
			bySeverity.merge(a.getSeverity() == null ? "(none)" : a.getSeverity(), 1L, Long::sum);
			if (a.getAcknowledgedAt() != null) acked++;
			if (a.getDisposition() != null) disposed++;
		}
		Map<String, Object> out = new java.util.LinkedHashMap<>();
		out.put("since_hours", sinceHours);
		out.put("total", rows.size());
		out.put("by_equipment", byEquipment);
		out.put("by_status", byStatus);
		out.put("by_severity", bySeverity);
		out.put("acked", acked);
		out.put("disposed", disposed);
		out.put("ack_rate", rows.isEmpty() ? 0.0 : Math.round(acked * 1000.0 / rows.size()) / 1000.0);
		return ApiResponse.ok(out);
	}

	/** One alarm's full diagnosis (Coordinator's get_alarm_detail). */
	@GetMapping("/{id}")
	public ApiResponse<AlarmDtos.Detail> detail(@PathVariable Long id) {
		AlarmEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("alarm"));
		return ApiResponse.ok(enrichment.enrichDetail(e));
	}

	@PostMapping
	@Transactional
	public ApiResponse<Dto> create(@Validated @RequestBody CreateRequest req) {
		AlarmEntity e = new AlarmEntity();
		e.setSkillId(req.skillId());
		if (req.triggerEvent() != null) e.setTriggerEvent(req.triggerEvent());
		if (req.equipmentId() != null) e.setEquipmentId(req.equipmentId());
		if (req.lotId() != null) e.setLotId(req.lotId());
		e.setStep(req.step());
		e.setEventTime(req.eventTime());
		if (req.severity() != null) e.setSeverity(req.severity());
		if (req.title() != null) e.setTitle(req.title());
		e.setSummary(req.summary());
		e.setExecutionLogId(req.executionLogId());
		e.setDiagnosticLogId(req.diagnosticLogId());
		AlarmEntity saved = repository.save(e);
		// Phase 2 — fan out via scheduler (fail-open).
		scheduler.dispatchAlarm(saved.getId());
		return ApiResponse.ok(Dto.of(saved));
	}

	public record CreateRequest(@NotNull Long skillId, String triggerEvent, String equipmentId,
	                            String lotId, String step, OffsetDateTime eventTime,
	                            String severity, String title, String summary,
	                            Long executionLogId, Long diagnosticLogId) {}

	public record Dto(Long id, Long skillId, String severity, String title, String status,
	                  OffsetDateTime createdAt) {
		static Dto of(AlarmEntity e) {
			return new Dto(e.getId(), e.getSkillId(), e.getSeverity(), e.getTitle(),
					e.getStatus(), e.getCreatedAt());
		}
	}
}
