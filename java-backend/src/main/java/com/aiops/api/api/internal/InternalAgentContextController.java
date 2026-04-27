package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;

/**
 * Aggregates "current state" snapshots that the agent's load_context_node
 * injects into each chat turn (Spec: SPEC_context_engineering Part B).
 *
 * v1 returns active alarms only. ooc_tools and recent_triggers are wired
 * later when their underlying queries land.
 */
@RestController
@RequestMapping("/internal/agent-context-snapshot")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalAgentContextController {

	private static final int ALARM_LIMIT = 10;

	private final AlarmRepository alarmRepository;

	public InternalAgentContextController(AlarmRepository alarmRepository) {
		this.alarmRepository = alarmRepository;
	}

	@GetMapping
	public ApiResponse<Snapshot> get(
			@RequestParam(value = "selected_equipment_id", required = false) String selectedEquipmentId) {
		OffsetDateTime now = OffsetDateTime.now();

		List<AlarmEntity> rows = alarmRepository.findByStatusOrderByCreatedAtDesc("active");
		List<ActiveAlarm> alarms = new ArrayList<>();
		for (int i = 0; i < Math.min(rows.size(), ALARM_LIMIT); i++) {
			AlarmEntity e = rows.get(i);
			long ageSeconds = e.getCreatedAt() == null ? 0
					: Duration.between(e.getCreatedAt().toInstant(), now.toInstant()).getSeconds();
			alarms.add(new ActiveAlarm(
					e.getId(),
					nullIfBlank(e.getEquipmentId()),
					nullIfBlank(e.getStep()),
					nullIfBlank(e.getSeverity()),
					nullIfBlank(e.getTitle()),
					ageSeconds));
		}

		ClientFocus focus = (selectedEquipmentId == null || selectedEquipmentId.isBlank())
				? null
				: new ClientFocus(selectedEquipmentId);

		return ApiResponse.ok(new Snapshot(now, alarms, focus));
	}

	private static String nullIfBlank(String s) {
		return (s == null || s.isBlank()) ? null : s;
	}

	public record Snapshot(OffsetDateTime asOf, List<ActiveAlarm> activeAlarms, ClientFocus userFocus) {}

	public record ActiveAlarm(Long id, String equipmentId, String step,
	                          String severity, String title, long ageSeconds) {}

	public record ClientFocus(String selectedEquipmentId) {}
}
