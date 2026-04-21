package com.aiops.api.api.auth;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.JwtService;
import com.aiops.api.auth.Role;
import com.aiops.api.auth.UserAccountService;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.config.AiopsProperties;
import jakarta.validation.constraints.NotBlank;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.Map;
import java.util.Set;

@RestController
@RequestMapping("/api/v1/auth")
public class AuthController {

	private final UserAccountService userAccountService;
	private final JwtService jwtService;
	private final AiopsProperties props;

	public AuthController(UserAccountService userAccountService,
	                      JwtService jwtService,
	                      AiopsProperties props) {
		this.userAccountService = userAccountService;
		this.jwtService = jwtService;
		this.props = props;
	}

	@PostMapping("/login")
	public ApiResponse<Map<String, Object>> login(@org.springframework.validation.annotation.Validated
	                                               @RequestBody LoginRequest req) {
		if (props.auth().mode() != AiopsProperties.Auth.Mode.local) {
			throw ApiException.badRequest("local login disabled — server is configured for OIDC");
		}
		AuthPrincipal principal = userAccountService.authenticate(req.username(), req.password());
		String token = jwtService.issue(principal);
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
			return ApiResponse.ok(Map.of(
					"id", ap.userId(),
					"username", ap.username(),
					"roles", ap.roles().stream().map(Enum::name).toList()
			));
		}
		// OIDC path — principal is a Jwt with subject claim
		Set<Role> roles = Set.of();
		return ApiResponse.ok(Map.of(
				"username", authentication.getName(),
				"roles", roles.stream().map(Enum::name).toList()
		));
	}

	public record LoginRequest(@NotBlank String username, @NotBlank String password) {}
}
