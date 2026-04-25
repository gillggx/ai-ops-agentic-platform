package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.system.SystemParameterEntity;
import com.aiops.api.domain.system.SystemParameterRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

/**
 * Read-only system parameter lookup for the sidecar's {@code load_context}
 * node, which fetches the {@code agent_soul} canonical override applied to
 * the system prompt.
 */
@RestController
@RequestMapping("/internal/system-parameters")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalSystemParameterController {

	private final SystemParameterRepository repository;

	public InternalSystemParameterController(SystemParameterRepository repository) {
		this.repository = repository;
	}

	@GetMapping("/{key}")
	public ApiResponse<Dto> get(@PathVariable String key) {
		SystemParameterEntity e = repository.findByKey(key).orElse(null);
		if (e == null) {
			return ApiResponse.ok(new Dto(null, key, null, null));
		}
		return ApiResponse.ok(Dto.of(e));
	}

	public record Dto(Long id, String key, String value, String description) {
		static Dto of(SystemParameterEntity e) {
			return new Dto(e.getId(), e.getKey(), e.getValue(), e.getDescription());
		}
	}
}
