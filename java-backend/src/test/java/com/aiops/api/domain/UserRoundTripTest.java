package com.aiops.api.domain;

import com.aiops.api.domain.user.UserEntity;
import com.aiops.api.domain.user.UserRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.annotation.Transactional;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@ActiveProfiles("test")
@Transactional
class UserRoundTripTest {

	@Autowired UserRepository userRepo;

	@Test
	@DisplayName("UserEntity save + findByUsername round-trip populates all columns correctly")
	void userRoundTrip() {
		UserEntity u = new UserEntity();
		u.setUsername("phase1_smoke_" + System.nanoTime());
		u.setEmail(u.getUsername() + "@example.com");
		u.setHashedPassword("$2a$12$fake");
		u.setRoles("[\"PE\"]");
		UserEntity saved = userRepo.save(u);

		assertThat(saved.getId()).isNotNull();
		assertThat(saved.getCreatedAt()).isNotNull();
		assertThat(saved.getUpdatedAt()).isNotNull();
		assertThat(saved.getIsActive()).isTrue();
		assertThat(saved.getIsSuperuser()).isFalse();
		assertThat(saved.getRoles()).isEqualTo("[\"PE\"]");

		Optional<UserEntity> found = userRepo.findByUsername(u.getUsername());
		assertThat(found).isPresent();
		assertThat(found.get().getEmail()).isEqualTo(u.getEmail());
	}
}
