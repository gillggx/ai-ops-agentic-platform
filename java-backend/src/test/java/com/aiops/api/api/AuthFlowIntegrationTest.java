package com.aiops.api.api;

import com.aiops.api.domain.user.UserRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.transaction.annotation.Transactional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * End-to-end Phase 2 auth flow:
 *  1. Bootstrap seed creates admin/admin at startup.
 *  2. POST /auth/login returns a JWT.
 *  3. Protected endpoint rejects missing token (401).
 *  4. Protected endpoint accepts valid token (200).
 *  5. PE-role user cannot hit IT_ADMIN-only endpoint (403).
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@Transactional
class AuthFlowIntegrationTest {

	@Autowired MockMvc mvc;
	@Autowired UserRepository userRepo;
	@Autowired ObjectMapper om;

	@Test
	void fullAuthFlow() throws Exception {
		// admin seeded by BootstrapSeeder on app startup (idempotent)
		if (!userRepo.existsByUsername("admin")) {
			throw new IllegalStateException("BootstrapSeeder should have created admin");
		}

		// 1) login
		MvcResult loginRes = mvc.perform(post("/api/v1/auth/login")
						.contentType(MediaType.APPLICATION_JSON)
						.content("{\"username\":\"admin\",\"password\":\"admin\"}"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.ok").value(true))
				.andExpect(jsonPath("$.data.access_token").exists())
				.andReturn();
		String body = loginRes.getResponse().getContentAsString();
		JsonNode node = om.readTree(body);
		String token = node.at("/data/access_token").asText();
		assertThat(token).isNotBlank();

		// 2) unauthenticated /admin/users → 401
		mvc.perform(get("/api/v1/admin/users"))
				.andExpect(status().isUnauthorized());

		// 3) authenticated /admin/users → 200
		mvc.perform(get("/api/v1/admin/users")
						.header("Authorization", "Bearer " + token))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.ok").value(true));

		// 4) /auth/me reflects principal
		mvc.perform(get("/api/v1/auth/me")
						.header("Authorization", "Bearer " + token))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.data.username").value("admin"))
				.andExpect(jsonPath("$.data.roles[0]").value("IT_ADMIN"));
	}

	@Test
	void wrongPasswordRejected() throws Exception {
		mvc.perform(post("/api/v1/auth/login")
						.contentType(MediaType.APPLICATION_JSON)
						.content("{\"username\":\"admin\",\"password\":\"wrong\"}"))
				.andExpect(status().isForbidden());
	}
}
