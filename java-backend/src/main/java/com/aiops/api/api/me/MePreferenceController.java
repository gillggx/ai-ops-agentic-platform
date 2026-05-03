package com.aiops.api.api.me;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.user.UserPreferenceEntity;
import com.aiops.api.domain.user.UserPreferenceRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

/**
 * Self-serve user preference endpoints — every logged-in user can read /
 * write their OWN row in {@code user_preferences}. This is the public
 * (JWT-gated) counterpart of {@code /internal/user-preferences/{userId}},
 * which the sidecar uses to read a user's preferences during context load.
 *
 * <p>Used by the Chart Catalog (/help/charts) "儲存為我的預設樣式"
 * button to persist a user's chart theme. The {@code preferences} column
 * is a free-form JSON text owned by the frontend; we don't validate the
 * shape here — frontend can extend it (chart_theme, dashboard_layout,
 * notification_pref…) without backend changes.
 */
@RestController
@RequestMapping("/api/v1/me/preferences")
@PreAuthorize(Authorities.ANY_ROLE)
public class MePreferenceController {

	private final UserPreferenceRepository repository;

	public MePreferenceController(UserPreferenceRepository repository) {
		this.repository = repository;
	}

	@GetMapping
	public ApiResponse<Dto> get(@AuthenticationPrincipal AuthPrincipal actor) {
		if (actor == null) throw ApiException.forbidden("authentication required");
		UserPreferenceEntity e = repository.findByUserId(actor.userId()).orElse(null);
		if (e == null) {
			return ApiResponse.ok(new Dto(null, actor.userId(), null, null));
		}
		return ApiResponse.ok(Dto.of(e));
	}

	@PutMapping
	@Transactional
	public ApiResponse<Dto> put(
		@AuthenticationPrincipal AuthPrincipal actor,
		@RequestBody PutRequest req
	) {
		if (actor == null) throw ApiException.forbidden("authentication required");
		// Upsert by user_id (unique index)
		UserPreferenceEntity e = repository.findByUserId(actor.userId()).orElseGet(() -> {
			UserPreferenceEntity fresh = new UserPreferenceEntity();
			fresh.setUserId(actor.userId());
			return fresh;
		});
		// Only the `preferences` JSON is user-editable here. soul_override is
		// admin-controlled (touching that requires the IT_ADMIN-gated
		// /api/v1/admin/users path, not this self-serve endpoint).
		if (req.preferences() != null) {
			e.setPreferences(req.preferences());
		}
		UserPreferenceEntity saved = repository.save(e);
		return ApiResponse.ok(Dto.of(saved));
	}

	public record Dto(Long id, Long userId, String preferences, String soulOverride) {
		static Dto of(UserPreferenceEntity e) {
			return new Dto(e.getId(), e.getUserId(), e.getPreferences(), e.getSoulOverride());
		}
	}

	public record PutRequest(String preferences) {}
}
