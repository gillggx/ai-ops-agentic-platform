package com.aiops.api.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "aiops")
public record AiopsProperties(
		Auth auth,
		Oidc oidc,
		Sidecar sidecar,
		Internal internal,
		Audit audit,
		Cors cors) {

	public record Auth(Mode mode, Jwt jwt) {
		public enum Mode { local, oidc }
	}

	public record Jwt(String secret, int expiryMinutes, String issuer) {}

	public record Oidc(String issuer, String clientId, String clientSecret, String roleClaim, String jwkSetUri) {}

	public record Sidecar(Python python) {}

	public record Python(String baseUrl, String serviceToken, int connectTimeoutMs, int readTimeoutMs) {}

	/** Reverse direction: Python sidecar calling back into Java. */
	public record Internal(String token, String allowedCallerIps) {}

	public record Audit(int retentionDays, int asyncQueueSize) {}

	public record Cors(String allowedOrigins) {}
}
