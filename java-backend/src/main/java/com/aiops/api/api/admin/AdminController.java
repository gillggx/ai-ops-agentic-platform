package com.aiops.api.api.admin;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Role;
import com.aiops.api.auth.SegregationOfDuties;
import com.aiops.api.auth.UserAccountService;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.user.UserEntity;
import com.aiops.api.domain.user.UserRepository;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.EnumSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * IT_ADMIN-only endpoints: user management, platform operations.
 * SPEC §2.6.2 — only role capable of POST /users.
 */
@RestController
@RequestMapping("/api/v1/admin")
@PreAuthorize("hasRole('IT_ADMIN')")
public class AdminController {

	private final UserAccountService userAccountService;
	private final UserRepository userRepository;

	public AdminController(UserAccountService userAccountService, UserRepository userRepository) {
		this.userAccountService = userAccountService;
		this.userRepository = userRepository;
	}

	@GetMapping("/users")
	public ApiResponse<List<Map<String, Object>>> listUsers() {
		List<Map<String, Object>> out = userRepository.findAll().stream()
				.map(u -> Map.<String, Object>of(
						"id", u.getId(),
						"username", u.getUsername(),
						"email", u.getEmail(),
						"is_active", u.getIsActive(),
						"roles", u.getRoles()))
				.toList();
		return ApiResponse.ok(out);
	}

	@PostMapping("/users")
	public ApiResponse<Map<String, Object>> createUser(
			@org.springframework.validation.annotation.Validated @RequestBody CreateUserRequest req,
			@AuthenticationPrincipal AuthPrincipal caller) {
		Set<Role> roles = EnumSet.noneOf(Role.class);
		req.roles().forEach(r -> Role.fromString(r).ifPresent(roles::add));
		SegregationOfDuties.validate(roles);
		UserEntity u = userAccountService.createUser(req.username(), req.email(), req.password(), roles);
		return ApiResponse.ok(Map.of(
				"id", u.getId(),
				"username", u.getUsername(),
				"email", u.getEmail(),
				"roles", u.getRoles(),
				"created_by", caller.username()
		));
	}

	public record CreateUserRequest(
			@NotBlank String username,
			@NotBlank @Email String email,
			@NotBlank String password,
			@NotEmpty List<String> roles) {}
}
