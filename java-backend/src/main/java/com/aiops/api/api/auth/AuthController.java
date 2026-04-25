package com.aiops.api.api.auth;

import com.aiops.api.audit.AuditLogService;
import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.JwtService;
import com.aiops.api.auth.Role;
import com.aiops.api.auth.UserAccountService;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.config.AiopsProperties;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.constraints.NotBlank;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

import java.util.Map;
import java.util.Set;

@RestController
@RequestMapping("/api/v1/auth")
public class AuthController {

	private final UserAccountService userAccountService;
	private final JwtService jwtService;
	private final AiopsProperties props;
	private final AuditLogService auditLogService;

	public AuthController(UserAccountService userAccountService,
	                      JwtService jwtService,
	                      AiopsProperties props,
	                      AuditLogService auditLogService) {
		this.userAccountService = userAccountService;
		this.jwtService = jwtService;
		this.props = props;
		this.auditLogService = auditLogService;
	}

	@PostMapping("/login")
	public ApiResponse<Map<String, Object>> login(@org.springframework.validation.annotation.Validated
	                                               @RequestBody LoginRequest req,
	                                               HttpServletRequest servletReq) {
		if (props.auth().mode() != AiopsProperties.Auth.Mode.local) {
			throw ApiException.badRequest("local login disabled — server is configured for OIDC");
		}
		AuthPrincipal principal;
		try {
			principal = userAccountService.authenticate(req.username(), req.password());
		} catch (ApiException ex) {
			// Failed login audit — pin the attempted username so brute-force shows up.
			auditLogService.record(servletReq, 403, 0L, null, "login failed for " + req.username());
			throw ex;
		}
		String token = jwtService.issue(principal);

		// Seed SecurityContext so AuditInterceptor.afterCompletion sees the real principal
		// even though /auth/login is permit-all.
		var auth = new UsernamePasswordAuthenticationToken(
				principal, null,
				principal.roles().stream()
						.map(r -> (org.springframework.security.core.GrantedAuthority) new SimpleGrantedAuthority(r.authority()))
						.toList());
		SecurityContextHolder.getContext().setAuthentication(auth);

		return ApiResponse.ok(Map.of(
				"token_type", "Bearer",
				"access_token", token,
				"user", Map.of(
						"id", principal.userId(),
						"username", principal.username(),
						"roles", principal.roles().stream().map(Enum::name).toList()
				)
		));
	}

	@GetMapping("/me")
	public ApiResponse<Map<String, Object>> me(Authentication authentication) {
		if (authentication == null || !authentication.isAuthenticated()) {
			throw ApiException.forbidden("not authenticated");
		}
		Object p = authentication.getPrincipal();
		if (p instanceof AuthPrincipal ap) {
			// Enrich with DB fields the principal doesn't carry (email / displayName / oidc_provider)
			var user = userAccountService.loadUserById(ap.userId());
			Map<String, Object> body = new java.util.HashMap<>();
			body.put("id", ap.userId());
			body.put("username", ap.username());
			body.put("email", user != null ? user.getEmail() : null);
			body.put("display_name", user != null && user.getDisplayName() != null
					? user.getDisplayName() : ap.username());
			body.put("roles", ap.roles().stream().map(Enum::name).toList());
			body.put("oidc_provider", user != null ? user.getOidcProvider() : null);
			return ApiResponse.ok(body);
		}
		// OIDC path — principal is a Jwt with subject claim
		Set<Role> roles = Set.of();
		return ApiResponse.ok(Map.of(
				"username", authentication.getName(),
				"roles", roles.stream().map(Enum::name).toList()
		));
	}

	@PutMapping("/me")
	public ApiResponse<Map<String, Object>> updateMe(@RequestBody UpdateProfileRequest req,
	                                                  @org.springframework.security.core.annotation.AuthenticationPrincipal AuthPrincipal principal) {
		if (principal == null) throw ApiException.forbidden("not authenticated");
		var user = userAccountService.updateDisplayName(principal.userId(), req.displayName());
		return ApiResponse.ok(Map.of(
				"id", user.getId(),
				"username", user.getUsername(),
				"email", user.getEmail(),
				"display_name", user.getDisplayName() != null ? user.getDisplayName() : user.getUsername()
		));
	}

	@PutMapping("/me/password")
	public ApiResponse<Map<String, Object>> changePassword(@org.springframework.validation.annotation.Validated
	                                                        @RequestBody ChangePasswordRequest req,
	                                                        @org.springframework.security.core.annotation.AuthenticationPrincipal AuthPrincipal principal) {
		if (principal == null) throw ApiException.forbidden("not authenticated");
		userAccountService.changePassword(principal.userId(), req.oldPassword(), req.newPassword());
		return ApiResponse.ok(Map.of("status", "changed"));
	}

	public record LoginRequest(@NotBlank String username, @NotBlank String password) {}
	public record UpdateProfileRequest(String displayName) {}
	public record ChangePasswordRequest(
			@NotBlank String oldPassword,
			@NotBlank String newPassword) {}
}
