package com.aiops.api.api.alarm;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.common.PageResponse;
import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.time.ZoneOffset;

/** Alarm Center endpoints. SPEC §2.6.2 — all 3 roles can read + ack. */
@RestController
@RequestMapping("/api/v1/alarms")
@PreAuthorize(Authorities.ANY_ROLE)
public class AlarmController {

	private final AlarmRepository repository;

	public AlarmController(AlarmRepository repository) {
		this.repository = repository;
	}

	@GetMapping
	public Object list(
			@RequestParam(required = false) String status,
			@RequestParam(defaultValue = "0") int page,
			@RequestParam(defaultValue = "50") int size,
			@RequestParam(defaultValue = "false") boolean paginated) {
		int safeSize = Math.min(Math.max(size, 1), 500);
		var pageable = PageRequest.of(page, safeSize, Sort.by(Sort.Direction.DESC, "createdAt"));
		Page<AlarmEntity> src = repository.findAll(pageable);
		java.util.List<AlarmDtos.Summary> items;
		if (status != null && !status.isBlank()) {
			items = src.getContent().stream()
					.filter(a -> status.equalsIgnoreCase(a.getStatus()))
					.map(AlarmDtos::summaryOf).toList();
		} else {
			items = src.getContent().stream().map(AlarmDtos::summaryOf).toList();
		}
		if (paginated) {
			return ApiResponse.ok(new PageResponse<>(src.getTotalElements(), page, safeSize, items));
		}
		// Python-compat default: direct array under data.
		return ApiResponse.ok(items);
	}

	@GetMapping("/{id}")
	public ApiResponse<AlarmDtos.Detail> get(@PathVariable Long id) {
		AlarmEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("alarm"));
		return ApiResponse.ok(AlarmDtos.detailOf(e));
	}

	@PostMapping("/{id}/ack")
	@Transactional
	public ApiResponse<AlarmDtos.Detail> ack(@PathVariable Long id,
	                                         @AuthenticationPrincipal AuthPrincipal caller) {
		AlarmEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("alarm"));
		if ("resolved".equalsIgnoreCase(e.getStatus())) {
			throw ApiException.conflict("alarm already resolved");
		}
		e.setStatus("acknowledged");
		e.setAcknowledgedBy(caller.username());
		e.setAcknowledgedAt(OffsetDateTime.now(ZoneOffset.UTC));
		return ApiResponse.ok(AlarmDtos.detailOf(repository.save(e)));
	}

	@PostMapping("/{id}/resolve")
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<AlarmDtos.Detail> resolve(@PathVariable Long id) {
		AlarmEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("alarm"));
		e.setStatus("resolved");
		e.setResolvedAt(OffsetDateTime.now(ZoneOffset.UTC));
		return ApiResponse.ok(AlarmDtos.detailOf(repository.save(e)));
	}
}
