package com.aiops.api.auth;

import com.aiops.api.common.ApiException;

import java.util.Set;

/**
 * Segregation-of-duties rules (SPEC §2.6.4).
 *
 * <ul>
 *   <li>IT_ADMIN must not also hold PE — the person who configures the platform
 *       cannot build skills on it (prevents self-approval).</li>
 *   <li>ON_DUTY must not be combined with any other role — read-only duty only.</li>
 *   <li>At least one role required.</li>
 * </ul>
 */
public final class SegregationOfDuties {

	private SegregationOfDuties() {}

	public static void validate(Set<Role> roles) {
		if (roles == null || roles.isEmpty()) {
			throw ApiException.badRequest("at least one role required");
		}
		if (roles.contains(Role.IT_ADMIN) && roles.contains(Role.PE)) {
			throw ApiException.badRequest("IT_ADMIN and PE cannot be assigned to the same user (SOD)");
		}
		if (roles.contains(Role.ON_DUTY) && roles.size() > 1) {
			throw ApiException.badRequest("ON_DUTY is read-only and cannot combine with other roles");
		}
	}
}
