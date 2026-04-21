package com.aiops.api.auth;

/**
 * Granted-authority string for service-to-service calls from the Python
 * sidecar. Used in {@code @PreAuthorize("hasAuthority(InternalAuthority.PYTHON_SIDECAR)")}
 * on {@code /internal/*} endpoints.
 */
public final class InternalAuthority {

	private InternalAuthority() {}

	/** Authority granted to requests bearing a valid {@code X-Internal-Token}. */
	public static final String PYTHON_SIDECAR = "SERVICE_PYTHON_SIDECAR";

	/** SpEL expression for use in {@code @PreAuthorize}. */
	public static final String REQUIRE_SIDECAR = "hasAuthority('" + PYTHON_SIDECAR + "')";
}
