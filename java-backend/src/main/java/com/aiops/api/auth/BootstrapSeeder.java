package com.aiops.api.auth;

import com.aiops.api.config.AiopsProperties;
import com.aiops.api.domain.user.UserRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

import java.util.EnumSet;

/**
 * First-boot seed for local auth:
 * if no users exist, create an {@code admin} account with role IT_ADMIN.
 * Skipped when running in OIDC mode (Azure AD manages identity there).
 */
@Slf4j
@Component
public class BootstrapSeeder {

	private final UserRepository userRepository;
	private final UserAccountService userAccountService;
	private final AiopsProperties props;

	public BootstrapSeeder(UserRepository userRepository,
	                       UserAccountService userAccountService,
	                       AiopsProperties props) {
		this.userRepository = userRepository;
		this.userAccountService = userAccountService;
		this.props = props;
	}

	@EventListener(ApplicationReadyEvent.class)
	public void seed() {
		if (props.auth().mode() != AiopsProperties.Auth.Mode.local) {
			log.info("Skipping local user seed (auth mode = {})", props.auth().mode());
			return;
		}
		if (userRepository.count() > 0) {
			log.info("Users already present ({}), skipping seed", userRepository.count());
			return;
		}
		userAccountService.createUser(
				"admin",
				"admin@aiops.local",
				"admin",
				EnumSet.of(Role.IT_ADMIN));
		log.warn("Seeded default IT_ADMIN user admin/admin — change password before production use");
	}
}
