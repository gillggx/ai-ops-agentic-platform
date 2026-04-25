package com.aiops.api.api.admin;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.auth.Role;
import com.aiops.api.auth.RoleCodec;
import com.aiops.api.auth.SegregationOfDuties;
import com.aiops.api.auth.UserAccountService;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.user.RoleChangeLogEntity;
import com.aiops.api.domain.user.RoleChangeLogRepository;
import com.aiops.api.domain.user.UserEntity;
import com.aiops.api.domain.user.UserRepository;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.util.*;
import java.util.stream.Collectors;

/**
 * Admin-only user management:
 *   GET    /api/v1/admin/users                   — list
 *   PUT    /api/v1/admin/users/{id}/roles        — change roles (audited)
 *   PUT    /api/v1/admin/users/{id}/active       — deactivate / reactivate
 *   GET    /api/v1/admin/users/{id}/role-history — who changed roles when
 *
 * Only IT_ADMIN can call. Self-demote is blocked server-side to prevent the
 * last admin accidentally locking themselves out.
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/admin/users")
@PreAuthorize(Authorities.ADMIN)
public class UsersController {

	private final UserRepository userRepository;
	private final RoleChangeLogRepository logRepository;
	private final RoleCodec roleCodec;
	private final UserAccountService userAccountService;

	public UsersController(UserRepository userRepository,
	                       RoleChangeLogRepository logRepository,
	                       RoleCodec roleCodec,
	                       UserAccountService userAccountService) {
		this.userRepository = userRepository;
		this.logRepository = logRepository;
		this.roleCodec = roleCodec;
		this.userAccountService = userAccountService;
	}

	@PostMapping
	@Transactional
	public ApiResponse<UserDto> createUser(@Validated @RequestBody CreateUserRequest req,
	                                        @AuthenticationPrincipal AuthPrincipal actor) {
		Set<Role> roles = parseRoles(req.roles());
		SegregationOfDuties.validate(roles);
		UserEntity u = userAccountService.createUser(req.username(), req.email(), req.password(), roles);
		log.info("actor user_id={} created local user {} with roles {}",
				actor != null ? actor.userId() : "system", u.getUsername(), roles);
		return ApiResponse.ok(toDto(u));
	}

	@GetMapping
	public ApiResponse<List<UserDto>> list() {
		var all = userRepository.findAll();
		return ApiResponse.ok(all.stream()
				.sorted(Comparator.comparing(UserEntity::getId))
				.map(this::toDto)
				.toList());
	}

	@PutMapping("/{id}/roles")
	@Transactional
	public ApiResponse<UserDto> updateRoles(@PathVariable Long id,
	                                         @RequestBody UpdateRolesRequest req,
	                                         @AuthenticationPrincipal AuthPrincipal actor) {
		UserEntity user = userRepository.findById(id)
				.orElseThrow(() -> ApiException.notFound("user"));

		Set<Role> newRoles = parseRoles(req.roles());
		if (newRoles.isEmpty()) {
			throw ApiException.badRequest("roles cannot be empty");
		}

		// Safety: actor cannot remove their own IT_ADMIN role — prevents
		// self-lockout when there's only one admin left.
		if (actor != null
				&& Long.valueOf(actor.userId()).equals(user.getId())
				&& actor.roles().contains(Role.IT_ADMIN)
				&& !newRoles.contains(Role.IT_ADMIN)) {
			throw ApiException.badRequest("cannot remove your own IT_ADMIN role — have another admin do it");
		}

		Set<Role> oldRoles = roleCodec.decode(user.getRoles());
		String oldRolesJson = user.getRoles();
		user.setRoles(roleCodec.encode(newRoles));
		user.setIsSuperuser(newRoles.contains(Role.IT_ADMIN));
		user = userRepository.save(user);

		var logEntry = new RoleChangeLogEntity();
		logEntry.setTargetUserId(user.getId().intValue());
		logEntry.setActorUserId(actor != null ? Long.valueOf(actor.userId()).intValue() : null);
		logEntry.setOldRoles(oldRolesJson);
		logEntry.setNewRoles(user.getRoles());
		logEntry.setReason(req.reason());
		logEntry.setChangedAt(OffsetDateTime.now());
		logRepository.save(logEntry);

		log.info("actor user_id={} changed user_id={} roles: {} → {}",
				actor != null ? actor.userId() : "system", user.getId(), oldRoles, newRoles);
		return ApiResponse.ok(toDto(user));
	}

	@PutMapping("/{id}/active")
	@Transactional
	public ApiResponse<UserDto> setActive(@PathVariable Long id,
	                                       @RequestBody SetActiveRequest req,
	                                       @AuthenticationPrincipal AuthPrincipal actor) {
		UserEntity user = userRepository.findById(id)
				.orElseThrow(() -> ApiException.notFound("user"));
		if (actor != null && Long.valueOf(actor.userId()).equals(user.getId())
				&& Boolean.FALSE.equals(req.isActive())) {
			throw ApiException.badRequest("cannot deactivate yourself");
		}
		user.setIsActive(req.isActive() != null ? req.isActive() : Boolean.TRUE);
		user = userRepository.save(user);
		return ApiResponse.ok(toDto(user));
	}

	@GetMapping("/{id}/role-history")
	public ApiResponse<List<RoleChangeLogDto>> roleHistory(@PathVariable Long id) {
		var logs = logRepository.findByTargetUserIdOrderByChangedAtDesc(id.intValue());
		return ApiResponse.ok(logs.stream().map(this::toLogDto).toList());
	}

	// ── helpers ────────────────────────────────────────────────────────

	private Set<Role> parseRoles(List<String> in) {
		if (in == null) return Collections.emptySet();
		return in.stream()
				.map(Role::fromString)
				.filter(Optional::isPresent)
				.map(Optional::get)
				.collect(Collectors.toCollection(() -> EnumSet.noneOf(Role.class)));
	}

	private UserDto toDto(UserEntity u) {
		return new UserDto(
				u.getId(), u.getUsername(), u.getEmail(),
				roleCodec.decode(u.getRoles()).stream().map(Enum::name).sorted().toList(),
				Boolean.TRUE.equals(u.getIsActive()),
				u.getOidcProvider(),
				u.getLastLoginAt()
		);
	}

	private RoleChangeLogDto toLogDto(RoleChangeLogEntity e) {
		return new RoleChangeLogDto(
				e.getId(), e.getTargetUserId(), e.getActorUserId(),
				e.getOldRoles(), e.getNewRoles(), e.getReason(), e.getChangedAt()
		);
	}

	// ── DTOs ──────────────────────────────────────────────────────────

	public record UserDto(Long id, String username, String email, List<String> roles,
	                      Boolean isActive, String oidcProvider, OffsetDateTime lastLoginAt) {}

	public record UpdateRolesRequest(List<String> roles, String reason) {}

	public record SetActiveRequest(Boolean isActive) {}

	public record RoleChangeLogDto(Long id, Integer targetUserId, Integer actorUserId,
	                                String oldRoles, String newRoles, String reason,
	                                OffsetDateTime changedAt) {}

	public record CreateUserRequest(
			@NotBlank String username,
			@NotBlank @Email String email,
			@NotBlank String password,
			@NotEmpty List<String> roles) {}
}
