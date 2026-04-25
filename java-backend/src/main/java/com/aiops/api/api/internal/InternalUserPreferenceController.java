package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.user.UserPreferenceEntity;
import com.aiops.api.domain.user.UserPreferenceRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

/**
 * Read-only access to user_preferences for the Python sidecar's
 * {@code load_context} node, which loads per-user soul_override + preferences
 * to specialise the agent system prompt.
 *
 * <p>Public CRUD lives at {@code /api/v1/user-preferences} (admin only); this
 * is the sidecar-side read path that bypasses the user-JWT gate via
 * {@code X-Internal-Token}.
 */
@RestController
@RequestMapping("/internal/user-preferences")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalUserPreferenceController {

	private final UserPreferenceRepository repository;

	public InternalUserPreferenceController(UserPreferenceRepository repository) {
		this.repository = repository;
	}

	@GetMapping("/{userId}")
	public ApiResponse<Dto> get(@PathVariable Long userId) {
		UserPreferenceEntity e = repository.findByUserId(userId).orElse(null);
		if (e == null) {
			return ApiResponse.ok(new Dto(null, userId, null, null));
		}
		return ApiResponse.ok(Dto.of(e));
	}

	public record Dto(Long id, Long userId, String preferences, String soulOverride) {
		static Dto of(UserPreferenceEntity e) {
			return new Dto(e.getId(), e.getUserId(), e.getPreferences(), e.getSoulOverride());
		}
	}
}
