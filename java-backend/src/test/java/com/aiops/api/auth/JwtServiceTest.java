package com.aiops.api.auth;

import com.auth0.jwt.exceptions.JWTVerificationException;
import com.aiops.api.config.AiopsProperties;
import org.junit.jupiter.api.Test;

import java.util.EnumSet;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class JwtServiceTest {

	private static AiopsProperties props(String secret, int expiryMinutes) {
		return new AiopsProperties(
				new AiopsProperties.Auth(AiopsProperties.Auth.Mode.local,
						new AiopsProperties.Jwt(secret, expiryMinutes, "aiops-api-test")),
				new AiopsProperties.Oidc("", "", "", "roles", ""),
				new AiopsProperties.Sidecar(new AiopsProperties.Python("http://x", "t", 1000, 1000)),
				new AiopsProperties.Internal("dev-internal-token", "127.0.0.1"),
				new AiopsProperties.Audit(90, 100),
				new AiopsProperties.Cors("http://localhost"));
	}

	@Test
	void issueAndVerifyRoundTrip() {
		JwtService svc = new JwtService(props("0123456789abcdef0123456789abcdef", 5));
		AuthPrincipal p = new AuthPrincipal(42L, "alice", EnumSet.of(Role.PE, Role.ON_DUTY));
		// Note: production code would not combine PE+ON_DUTY — SOD would reject,
		// but JwtService itself doesn't enforce that; just tests codec fidelity.
		String token = svc.issue(p);
		assertThat(token).startsWith("eyJ");

		AuthPrincipal verified = svc.verify(token);
		assertThat(verified.userId()).isEqualTo(42L);
		assertThat(verified.username()).isEqualTo("alice");
		assertThat(verified.roles()).containsExactlyInAnyOrder(Role.PE, Role.ON_DUTY);
	}

	@Test
	void shortSecretRejected() {
		assertThatThrownBy(() -> new JwtService(props("short", 5)))
				.isInstanceOf(IllegalStateException.class);
	}

	@Test
	void tamperedTokenRejected() {
		JwtService svc = new JwtService(props("0123456789abcdef0123456789abcdef", 5));
		String token = svc.issue(new AuthPrincipal(1L, "bob", EnumSet.of(Role.IT_ADMIN)));
		String tampered = token.substring(0, token.length() - 4) + "ZZZZ";
		assertThatThrownBy(() -> svc.verify(tampered))
				.isInstanceOf(JWTVerificationException.class);
	}
}
