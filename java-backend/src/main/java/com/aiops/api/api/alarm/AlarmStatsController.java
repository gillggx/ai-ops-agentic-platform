package com.aiops.api.api.alarm;

import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.EnumMap;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Alarm Center dashboard counts.
 * Python returned {{"critical": n, "high": n, "medium": n, "low": n, "total": n}};
 * we mirror that shape exactly so Frontend dashboard widget keeps working.
 */
@RestController
@RequestMapping("/api/v1/alarms/stats")
@PreAuthorize(Authorities.ANY_ROLE)
public class AlarmStatsController {

	private final AlarmRepository repository;

	public AlarmStatsController(AlarmRepository repository) {
		this.repository = repository;
	}

	@GetMapping
	public ApiResponse<Map<String, Long>> stats(@RequestParam(required = false) String status) {
		List<AlarmEntity> rows = (status != null && !status.isBlank())
				? repository.findByStatusOrderByCreatedAtDesc(status)
				: repository.findAll();
		Map<String, Long> counts = new HashMap<>();
		for (String sev : List.of("critical", "high", "medium", "low")) counts.put(sev, 0L);
		long total = 0L;
		for (AlarmEntity a : rows) {
			total++;
			String sev = a.getSeverity() == null ? "medium" : a.getSeverity().toLowerCase(Locale.ROOT);
			counts.merge(sev, 1L, Long::sum);
		}
		counts.put("total", total);
		return ApiResponse.ok(counts);
	}
}
