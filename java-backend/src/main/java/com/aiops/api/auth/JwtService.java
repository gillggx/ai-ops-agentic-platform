package com.aiops.api.auth;

import com.auth0.jwt.JWT;
import com.auth0.jwt.JWTVerifier;
import com.auth0.jwt.algorithms.Algorithm;
import com.auth0.jwt.exceptions.JWTVerificationException;
import com.auth0.jwt.interfaces.DecodedJWT;
import com.aiops.api.config.AiopsProperties;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Date;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Issues + verifies local-auth JWTs. Used when {@code aiops.auth.mode=local}.
 * For {@code oidc} mode, Spring's OAuth2 resource server handles verification
 * against the Azure AD issuer instead.
 */
@Service
public class JwtService {

	private static final String CLAIM_USER_ID = "uid";
	private static final String CLAIM_ROLES = "roles";

	private final Algorithm algorithm;
	private final String issuer;
	private final long expirySeconds;
	private final JWTVerifier verifier;

	public JwtService(AiopsProperties props) {
		var jwt = props.auth().jwt();
		if (jwt.secret() == null || jwt.secret().length() < 32) {
			throw new IllegalStateException("aiops.auth.jwt.secret must be at least 32 chars");
		}
		this.algorithm = Algorithm.HMAC256(jwt.secret());
		this.issuer = jwt.issuer();
		this.expirySeconds = jwt.expiryMinutes() * 60L;
		this.verifier = JWT.require(algorithm).withIssuer(issuer).build();
	}

	public String issue(AuthPrincipal principal) {
		Instant now = Instant.now();
		return JWT.create()
				.withIssuer(issuer)
				.withSubject(principal.username())
				.withClaim(CLAIM_USER_ID, principal.userId())
				.withClaim(CLAIM_ROLES, principal.roles().stream().map(Enum::name).toList())
				.withIssuedAt(Date.from(now))
				.withExpiresAt(Date.from(now.plus(expirySeconds, ChronoUnit.SECONDS)))
				.sign(algorithm);
	}

	public AuthPrincipal verify(String token) throws JWTVerificationException {
		DecodedJWT jwt = verifier.verify(token);
		List<String> rawRoles = jwt.getClaim(CLAIM_ROLES).asList(String.class);
		Set<Role> roles = rawRoles == null
				? Set.of()
				: rawRoles.stream()
					.map(Role::fromString)
					.flatMap(java.util.Optional::stream)
					.collect(Collectors.toUnmodifiableSet());
		Long userId = jwt.getClaim(CLAIM_USER_ID).asLong();
		return new AuthPrincipal(userId, jwt.getSubject(), roles);
	}
}
