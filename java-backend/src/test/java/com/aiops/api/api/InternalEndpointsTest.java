package com.aiops.api.api;

import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.user.UserRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * Exercises the /internal/* chain — service-token required, no JWT.
 * Test profile picks up {@code JAVA_INTERNAL_TOKEN=dev-internal-token} default.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class InternalEndpointsTest {

	@Autowired MockMvc mvc;
	@Autowired PipelineRepository pipelineRepo;
	@Autowired UserRepository userRepo;
	@Autowired ObjectMapper om;

	private Long pipelineId;

	@BeforeEach
	void seed() {
		PipelineEntity p = new PipelineEntity();
		p.setName("internal_smoke_" + System.nanoTime());
		p.setDescription("for phase 5a test");
		p.setStatus("active");
		p.setPipelineJson("{\"nodes\":[{\"id\":\"n1\"},{\"id\":\"n2\"}]}");
		p = pipelineRepo.save(p);
		pipelineId = p.getId();
	}

	@Test
	void missingInternalTokenReturns401() throws Exception {
		mvc.perform(get("/internal/pipelines/" + pipelineId))
				.andExpect(status().isUnauthorized());
	}

	@Test
	void wrongInternalTokenReturns401() throws Exception {
		mvc.perform(get("/internal/pipelines/" + pipelineId)
						.header("X-Internal-Token", "wrong-one"))
				.andExpect(status().isUnauthorized());
	}

	@Test
	void validTokenReturnsPipelineWithDagJson() throws Exception {
		String body = mvc.perform(get("/internal/pipelines/" + pipelineId)
						.header("X-Internal-Token", "dev-internal-token"))
				.andExpect(status().isOk())
				.andReturn().getResponse().getContentAsString();
		JsonNode node = om.readTree(body);
		assertThat(node.at("/ok").asBoolean()).isTrue();
		assertThat(node.at("/data/id").asLong()).isEqualTo(pipelineId);
		assertThat(node.at("/data/pipelineJson").asText()).contains("n1").contains("n2");
	}

	@Test
	void jwtAuthRejectedOnInternal() throws Exception {
		// A regular JWT (via the normal auth flow) MUST NOT grant access to /internal/*.
		// We don't need to mint one — the filter only trusts X-Internal-Token.
		mvc.perform(get("/internal/pipelines/" + pipelineId)
						.header("Authorization", "Bearer some-jwt"))
				.andExpect(status().isUnauthorized());
	}

	@Test
	void executionLogPostRoundTrip() throws Exception {
		String body = mvc.perform(post("/internal/execution-logs")
						.header("X-Internal-Token", "dev-internal-token")
						.contentType(MediaType.APPLICATION_JSON)
						.content("{\"triggeredBy\":\"test\",\"status\":\"success\",\"durationMs\":42}"))
				.andExpect(status().isOk())
				.andReturn().getResponse().getContentAsString();
		JsonNode node = om.readTree(body);
		assertThat(node.at("/data/id").asLong()).isPositive();
		assertThat(node.at("/data/status").asText()).isEqualTo("success");
	}
}
