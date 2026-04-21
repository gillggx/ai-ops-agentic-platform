package com.aiops.api.api.admin;

import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.audit.AuditLogEntity;
import com.aiops.api.domain.audit.AuditLogRepository;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/admin/audit")
@PreAuthorize("hasRole('IT_ADMIN')")
public class AuditController {

	private final AuditLogRepository repository;

	public AuditController(AuditLogRepository repository) {
		this.repository = repository;
	}

	@GetMapping
	public ApiResponse<Map<String, Object>> list(
			@RequestParam(defaultValue = "0") int page,
			@RequestParam(defaultValue = "50") int size) {
		int safeSize = Math.min(Math.max(size, 1), 500);
		Page<AuditLogEntity> result = repository.findAll(
				PageRequest.of(page, safeSize, Sort.by(Sort.Direction.DESC, "createdAt")));
		List<Map<String, Object>> items = result.getContent().stream()
				.map(e -> Map.<String, Object>of(
						"id", e.getId(),
						"created_at", e.getCreatedAt(),
						"user_id", e.getUserId() == null ? -1 : e.getUserId(),
						"username", e.getUsername() == null ? "" : e.getUsername(),
						"roles", e.getRoles() == null ? "" : e.getRoles(),
						"method", e.getHttpMethod(),
						"endpoint", e.getEndpoint(),
						"status_code", e.getStatusCode() == null ? -1 : e.getStatusCode(),
						"duration_ms", e.getDurationMs() == null ? -1 : e.getDurationMs(),
						"remote_ip", e.getRemoteIp() == null ? "" : e.getRemoteIp()))
				.toList();
		return ApiResponse.ok(Map.of(
				"total", result.getTotalElements(),
				"page", result.getNumber(),
				"size", result.getSize(),
				"items", items));
	}
}
