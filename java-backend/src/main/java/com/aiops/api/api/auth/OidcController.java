package com.aiops.api.api.auth;

import com.aiops.api.audit.AuditLogService;
import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.JwtService;
import com.aiops.api.auth.Role;
import com.aiops.api.auth.RoleCodec;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.user.UserEntity;
import com.aiops.api.domain.user.UserRepository;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.constraints.NotBlank;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.util.EnumSet;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * OIDC identity bridge.
 *
 * Frontend NextAuth.js completes the OAuth2 Authorization Code flow against
 * the selected IdP (Azure AD / Google / Keycloak / Okta), gets an id_token,
 * and forwards the identity essentials to this endpoint:
 *
 *     POST /api/v1/auth/oidc-upsert
 *       { provider: "azure-ad", sub: "abc...", email: "...", name: "..." }
 *
 * We upsert a users row (keyed by provider+sub; falls back to email for the
 * first-time migration case where a local account already exists), then issue
 * our own local JWT. Frontend stores that JWT in a session cookie and attaches
 * it to subsequent Java calls — uniform with the local-credentials path.
 *
 * Auth: this endpoint MUST be callable without a prior JWT (that's the whole
 * point). We protect it with a shared secret env var (FRONTEND_UPSERT_TOKEN)
 * so random internet traffic can't self-register. The real access-control
 * gate is Frontend's NextAuth callback — only it ever POSTs here.
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/auth")
public class OidcController {

	private final UserRepository userRepository;
	private final JwtService jwtService;
	private final RoleCodec roleCodec;
	private final AuditLogService auditLogService;
	private final String upsertSharedSecret;

	public OidcController(UserRepository userRepository,
	                      JwtService jwtService,
	                      RoleCodec roleCodec,
	                      AuditLogService auditLogService,
	                      @Value("${aiops.oidc.upsert-secret:}") String upsertSharedSecret) {
		this.userRepository = userRepository;
		this.jwtService = jwtService;
		this.roleCodec = roleCodec;
		this.auditLogService = auditLogService;
		this.upsertSharedSecret = upsertSharedSecret;
	}

	@PostMapping("/oidc-upsert")
	@Transactional
	public ApiResponse<Map<String, Object>> upsert(@Validated @RequestBody UpsertRequest req,
	                                                HttpServletRequest servletReq) {
		// Protect against direct calls from outside NextAuth.
		String providedSecret = servletReq.getHeader("X-Upsert-Secret");
		if (upsertSharedSecret == null || upsertSharedSecret.isBlank()) {
			throw new com.aiops.api.common.ApiException(
					org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE,
					"oidc_not_configured",
					"aiops.oidc.upsert-secret is not set — this endpoint is disabled");
		}
		if (!upsertSharedSecret.equals(providedSecret)) {
			throw new com.aiops.api.common.ApiException(
					org.springframework.http.HttpStatus.FORBIDDEN,
					"forbidden",
					"invalid upsert secret");
		}

		String provider = req.provider().toLowerCase().trim();
		String sub = req.sub().trim();
		String email = req.email() == null ? null : req.email().trim().toLowerCase();

		// 1) Exact OIDC identity match → update lastLogin + return
		UserEntity user = userRepository.findByOidcProviderAndOidcSub(provider, sub).orElse(null);

		// 2) Email match → link existing local account to this IdP identity
		if (user == null && email != null && !email.isBlank()) {
			user = userRepository.findByEmail(email).orElse(null);
			if (user != null) {
				user.setOidcProvider(provider);
				user.setOidcSub(sub);
				log.info("Linked existing user {} to OIDC identity {}/{}", user.getUsername(), provider, sub);
			}
		}

		// 3) No match anywhere → create new user with default role ON_DUTY
		boolean created = false;
		if (user == null) {
			user = new UserEntity();
			String username = buildUsername(email, req.name(), sub);
			user.setUsername(username);
			user.setEmail(email != null && !email.isBlank() ? email : username + "@oidc.local");
			// Random bcrypt-sized password — user will never use it (OIDC-only account)
			user.setHashedPassword("$2a$12$" + UUID.randomUUID().toString().replace("-", "").substring(0, 53));
			user.setIsActive(Boolean.TRUE);
			user.setIsSuperuser(Boolean.FALSE);
			user.setRoles(roleCodec.encode(EnumSet.of(Role.ON_DUTY)));
			user.setOidcProvider(provider);
			user.setOidcSub(sub);
			created = true;
			log.info("Created new user {} via OIDC {}/{}", username, provider, sub);
		}

		user.setLastLoginAt(OffsetDateTime.now());
		user = userRepository.save(user);

		// Issue our JWT.
		Set<Role> roles = roleCodec.decode(user.getRoles());
		AuthPrincipal principal = new AuthPrincipal(user.getId(), user.getUsername(), roles);
		String token = jwtService.issue(principal);

		// Seed SecurityContext so audit log captures the action.
		var auth = new UsernamePasswordAuthenticationToken(
				principal, null,
				principal.roles().stream()
						.map(r -> (org.springframework.security.core.GrantedAuthority)
								new SimpleGrantedAuthority(r.authority()))
						.toList());
		SecurityContextHolder.getContext().setAuthentication(auth);

		auditLogService.record(servletReq, 200, 0L, null,
				(created ? "oidc_create" : "oidc_login") + ":" + provider + "/" + sub);

		return ApiResponse.ok(Map.of(
				"token_type", "Bearer",
				"access_token", token,
				"created", created,
				"user", Map.of(
						"id", user.getId(),
						"username", user.getUsername(),
						"email", user.getEmail(),
						"roles", roles.stream().map(Enum::name).toList()
				)
		));
	}

	/** Best-effort username: prefer email local-part → name → provider sub. */
	private String buildUsername(String email, String name, String sub) {
		if (email != null && email.contains("@")) {
			String candidate = email.substring(0, email.indexOf('@')).replaceAll("[^a-zA-Z0-9._-]", "");
			if (!candidate.isBlank() && !userRepository.existsByUsername(candidate)) return candidate;
			// suffix on collision
			String suffixed = candidate + "-" + sub.substring(0, Math.min(6, sub.length()));
			return suffixed;
		}
		if (name != null && !name.isBlank()) {
			String candidate = name.replaceAll("[^a-zA-Z0-9._-]", "");
			if (!candidate.isBlank() && !userRepository.existsByUsername(candidate)) return candidate;
		}
		return "user-" + sub.substring(0, Math.min(12, sub.length()));
	}

	public record UpsertRequest(
			@NotBlank String provider,   // "azure-ad" | "google" | "keycloak" | "okta"
			@NotBlank String sub,
			String email,
			String name) {}
}
