package com.aiops.api.auth;

import java.util.Set;

/** Authenticated caller extracted from a JWT or OIDC token. */
public record AuthPrincipal(Long userId, String username, Set<Role> roles) {

	public boolean hasRole(Role role) {
		return roles.contains(role);
	}
}
