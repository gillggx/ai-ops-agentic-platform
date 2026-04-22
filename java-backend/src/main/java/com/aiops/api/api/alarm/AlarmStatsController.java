package com.aiops.api.api.alarm;

import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.alarm.AlarmRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
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
		String statusParam = (status != null && !status.isBlank()) ? status : null;
		List<Object[]> grouped = repository.countBySeverityGrouped(statusParam);
		Map<String, Long> counts = new HashMap<>();
		for (String sev : List.of("critical", "high", "medium", "low")) counts.put(sev, 0L);
		long total = 0L;
		for (Object[] row : grouped) {
			String sev = String.valueOf(row[0]);
			long c = ((Number) row[1]).longValue();
			counts.merge(sev, c, Long::sum);
			total += c;
		}
		counts.put("total", total);
		return ApiResponse.ok(counts);
	}
}
