package com.aiops.api.api;

import com.aiops.api.auth.Role;
import com.aiops.api.auth.UserAccountService;
import com.aiops.api.domain.agent.AgentToolRepository;
import com.aiops.api.domain.mcp.DataSubjectRepository;
import com.aiops.api.domain.mcp.McpDefinitionRepository;
import com.aiops.api.domain.mcp.MockDataSourceRepository;
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

import java.util.EnumSet;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class Phase3cIntegrationTest {

	@Autowired MockMvc mvc;
	@Autowired UserRepository userRepo;
	@Autowired UserAccountService userAccountService;
	@Autowired DataSubjectRepository dsRepo;
	@Autowired McpDefinitionRepository mcpRepo;
	@Autowired MockDataSourceRepository mockRepo;
	@Autowired AgentToolRepository toolRepo;
	@Autowired ObjectMapper om;

	private String adminToken;
	private String peToken;

	@BeforeEach
	void setup() throws Exception {
		if (!userRepo.existsByUsername("pe_3c")) {
			userAccountService.createUser("pe_3c", "pe3c@x.com", "pe_pw", EnumSet.of(Role.PE));
		}
		adminToken = loginToken("admin", "admin");
		peToken = loginToken("pe_3c", "pe_pw");
	}

	private String loginToken(String u, String p) throws Exception {
		String body = mvc.perform(post("/api/v1/auth/login")
						.contentType(MediaType.APPLICATION_JSON)
						.content("{\"username\":\"" + u + "\",\"password\":\"" + p + "\"}"))
				.andExpect(status().isOk())
				.andReturn().getResponse().getContentAsString();
		return om.readTree(body).at("/data/access_token").asText();
	}

	@Test
	void dataSubjectPeCrud() throws Exception {
		String name = "phase3c_ds_" + System.nanoTime();
		String body = "{\"name\":\"" + name + "\",\"description\":\"ds\"}";
		String res = mvc.perform(post("/api/v1/data-subjects")
						.header("Authorization", "Bearer " + peToken)
						.contentType(MediaType.APPLICATION_JSON).content(body))
				.andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
		Long id = om.readTree(res).at("/data/id").asLong();

		try {
			// PE cannot delete (admin only)
			mvc.perform(delete("/api/v1/data-subjects/" + id)
							.header("Authorization", "Bearer " + peToken))
					.andExpect(status().isForbidden());
		} finally {
			dsRepo.findById(id).ifPresent(dsRepo::delete);
		}
	}

	@Test
	void mcpDefinitionAdminOnlyWrite() throws Exception {
		String name = "phase3c_mcp_" + System.nanoTime();
		String body = "{\"name\":\"" + name + "\",\"mcpType\":\"custom\",\"description\":\"x\"}";
		mvc.perform(post("/api/v1/mcp-definitions")
						.header("Authorization", "Bearer " + peToken)
						.contentType(MediaType.APPLICATION_JSON).content(body))
				.andExpect(status().isForbidden());

		String res = mvc.perform(post("/api/v1/mcp-definitions")
						.header("Authorization", "Bearer " + adminToken)
						.contentType(MediaType.APPLICATION_JSON).content(body))
				.andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
		Long id = om.readTree(res).at("/data/id").asLong();
		mcpRepo.deleteById(id);
	}

	@Test
	void agentToolOwnership() throws Exception {
		String peBody = "{\"name\":\"pe_tool\",\"code\":\"def run(x): return x\"}";
		String res = mvc.perform(post("/api/v1/agent-tools")
						.header("Authorization", "Bearer " + peToken)
						.contentType(MediaType.APPLICATION_JSON).content(peBody))
				.andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
		JsonNode node = om.readTree(res);
		Long peToolId = node.at("/data/id").asLong();

		try {
			// Admin sees 0 in its own list (it hasn't created any)
			mvc.perform(get("/api/v1/agent-tools")
							.header("Authorization", "Bearer " + adminToken))
					.andExpect(status().isOk())
					.andExpect(jsonPath("$.data.length()").value(0));

			// Admin cannot fetch PE's tool (403 — not owner)
			mvc.perform(get("/api/v1/agent-tools/" + peToolId)
							.header("Authorization", "Bearer " + adminToken))
					.andExpect(status().isForbidden());
		} finally {
			toolRepo.findById(peToolId).ifPresent(toolRepo::delete);
		}
	}

	@Test
	void mockDataSourceListReadable() throws Exception {
		mvc.perform(get("/api/v1/mock-data-sources")
						.header("Authorization", "Bearer " + peToken))
				.andExpect(status().isOk());
	}
}
