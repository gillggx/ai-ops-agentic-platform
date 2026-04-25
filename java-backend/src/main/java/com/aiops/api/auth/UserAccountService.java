package com.aiops.api.auth;

import com.aiops.api.common.ApiException;
import com.aiops.api.domain.user.UserEntity;
import com.aiops.api.domain.user.UserRepository;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.EnumSet;
import java.util.Set;

@Service
public class UserAccountService {

	private final UserRepository userRepository;
	private final PasswordEncoder passwordEncoder;
	private final RoleCodec roleCodec;

	public UserAccountService(UserRepository userRepository,
	                          PasswordEncoder passwordEncoder,
	                          RoleCodec roleCodec) {
		this.userRepository = userRepository;
		this.passwordEncoder = passwordEncoder;
		this.roleCodec = roleCodec;
	}

	@Transactional
	public UserEntity createUser(String username, String email, String rawPassword, Set<Role> roles) {
		if (userRepository.existsByUsername(username)) {
			throw ApiException.conflict("username already exists");
		}
		if (userRepository.existsByEmail(email)) {
			throw ApiException.conflict("email already exists");
		}
		SegregationOfDuties.validate(roles);

		UserEntity u = new UserEntity();
		u.setUsername(username);
		u.setEmail(email);
		u.setHashedPassword(passwordEncoder.encode(rawPassword));
		u.setIsActive(Boolean.TRUE);
		u.setIsSuperuser(roles.contains(Role.IT_ADMIN));
		u.setRoles(roleCodec.encode(roles));
		return userRepository.save(u);
	}

	@Transactional(readOnly = true)
	public AuthPrincipal authenticate(String username, String rawPassword) {
		UserEntity user = userRepository.findByUsername(username)
				.orElseThrow(() -> ApiException.forbidden("invalid credentials"));
		if (!Boolean.TRUE.equals(user.getIsActive())) {
			throw ApiException.forbidden("account disabled");
		}
		if (!passwordEncoder.matches(rawPassword, user.getHashedPassword())) {
			throw ApiException.forbidden("invalid credentials");
		}
		Set<Role> roles = roleCodec.decode(user.getRoles());
		return new AuthPrincipal(user.getId(), user.getUsername(), roles);
	}

	@Transactional(readOnly = true)
	public UserEntity loadUserById(Long id) {
		return userRepository.findById(id).orElse(null);
	}

	@Transactional(readOnly = true)
	public AuthPrincipal loadByUsername(String username) {
		UserEntity user = userRepository.findByUsername(username)
				.orElseThrow(() -> ApiException.forbidden("user not found"));
		return new AuthPrincipal(user.getId(), user.getUsername(), roleCodec.decode(user.getRoles()));
	}

	@Transactional(readOnly = true)
	public Set<Role> rolesOf(Long userId) {
		return userRepository.findById(userId)
				.map(u -> roleCodec.decode(u.getRoles()))
				.orElse(EnumSet.noneOf(Role.class));
	}

	/**
	 * Change password for a local account. Caller MUST be authenticated as
	 * the target user. Rejects OIDC-only accounts (no real password) and
	 * enforces a basic minimum length.
	 */
	@Transactional
	public void changePassword(Long userId, String oldPassword, String newPassword) {
		UserEntity user = userRepository.findById(userId)
				.orElseThrow(() -> ApiException.notFound("user"));
		if (user.getOidcProvider() != null && !user.getOidcProvider().isBlank()) {
			throw ApiException.badRequest(
					"此帳號透過 " + user.getOidcProvider() + " 登入，請到該識別提供者變更密碼");
		}
		if (!passwordEncoder.matches(oldPassword, user.getHashedPassword())) {
			throw ApiException.forbidden("舊密碼錯誤");
		}
		if (newPassword == null || newPassword.length() < 6) {
			throw ApiException.badRequest("新密碼長度至少 6 字元");
		}
		user.setHashedPassword(passwordEncoder.encode(newPassword));
		userRepository.save(user);
	}

	/** Update a user's display_name. Returns the updated entity. */
	@Transactional
	public UserEntity updateDisplayName(Long userId, String displayName) {
		UserEntity user = userRepository.findById(userId)
				.orElseThrow(() -> ApiException.notFound("user"));
		user.setDisplayName(displayName == null || displayName.isBlank()
				? user.getUsername() : displayName.trim());
		return userRepository.save(user);
	}
}
