package com.aiops.api.api.admin;

import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * IT_ADMIN-only endpoints placeholder.
 * Users management moved to UsersController (2026-04-25).
 */
@RestController
@RequestMapping("/api/v1/admin")
@PreAuthorize("hasRole('IT_ADMIN')")
public class AdminController {
	// Intentionally empty. Kept so that future IT_ADMIN-only features without
	// a natural home (e.g. feature-flag toggles) can attach here without
	// re-deriving the base path + role gate.
}
