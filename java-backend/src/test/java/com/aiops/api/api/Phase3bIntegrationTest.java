package com.aiops.api.api;

import com.aiops.api.auth.Role;
import com.aiops.api.auth.UserAccountService;
import com.aiops.api.domain.patrol.AutoPatrolRepository;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.skill.SkillDefinitionRepository;
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

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/** Phase 3b — Skill / Pipeline / AutoPatrol CRUD + role gating. */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class Phase3bIntegrationTest {

	@Autowired MockMvc mvc;
	@Autowired UserRepository userRepo;
	@Autowired UserAccountService userAccountService;
	@Autowired SkillDefinitionRepository skillRepo;
	@Autowired PipelineRepository pipelineRepo;
	@Autowired AutoPatrolRepository patrolRepo;
	@Autowired ObjectMapper om;

	private String adminToken;
	private String peToken;
	private String onDutyToken;

	@BeforeEach
	void setup() throws Exception {
		if (!userRepo.existsByUsername("pe_3b")) {
			userAccountService.createUser("pe_3b", "pe3b@x.com", "pe_pw", EnumSet.of(Role.PE));
		}
		if (!userRepo.existsByUsername("od_3b")) {
			userAccountService.createUser("od_3b", "od3b@x.com", "od_pw", EnumSet.of(Role.ON_DUTY));
		}
		adminToken = loginToken("admin", "admin");
		peToken = loginToken("pe_3b", "pe_pw");
		onDutyToken = loginToken("od_3b", "od_pw");
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
	void skillCrud() throws Exception {
		String name = "phase3b_skill_" + System.nanoTime();
		String body = "{\"name\":\"" + name + "\",\"description\":\"sk\",\"trigger_mode\":\"both\",\"source\":\"skill\"}";

		// On-duty cannot create
		mvc.perform(post("/api/v1/skills").header("Authorization", "Bearer " + onDutyToken)
						.contentType(MediaType.APPLICATION_JSON).content(body))
				.andExpect(status().isForbidden());

		String res = mvc.perform(post("/api/v1/skills").header("Authorization", "Bearer " + peToken)
						.contentType(MediaType.APPLICATION_JSON).content(body))
				.andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
		JsonNode node = om.readTree(res);
		Long id = node.at("/data/id").asLong();
		assertThat(node.at("/data/created_by").asLong()).isPositive();

		try {
			// List visible to on-duty
			mvc.perform(get("/api/v1/skills").header("Authorization", "Bearer " + onDutyToken))
					.andExpect(status().isOk());
			// Update by PE
			mvc.perform(put("/api/v1/skills/" + id).header("Authorization", "Bearer " + peToken)
							.contentType(MediaType.APPLICATION_JSON).content("{\"description\":\"updated\"}"))
					.andExpect(status().isOk())
					.andExpect(jsonPath("$.data.description").value("updated"));
		} finally {
			skillRepo.findById(id).ifPresent(skillRepo::delete);
		}
	}

	@Test
	void pipelineLockedCannotMutate() throws Exception {
		var p = new com.aiops.api.domain.pipeline.PipelineEntity();
		p.setName("phase3b_pipeline_" + System.nanoTime());
		p.setStatus("locked");
		p = pipelineRepo.save(p);
		Long id = p.getId();

		try {
			mvc.perform(put("/api/v1/pipelines/" + id).header("Authorization", "Bearer " + peToken)
							.contentType(MediaType.APPLICATION_JSON)
							.content("{\"description\":\"try\"}"))
					.andExpect(status().isConflict());
		} finally {
			pipelineRepo.deleteById(id);
		}
	}

	@Test
	void autoPatrolPeCreateAdminOnlyNoDelete() throws Exception {
		String body = "{\"name\":\"phase3b_patrol_" + System.nanoTime() + "\",\"triggerMode\":\"schedule\",\"cronExpr\":\"0 */5 * * * *\"}";
		String res = mvc.perform(post("/api/v1/auto-patrols").header("Authorization", "Bearer " + peToken)
						.contentType(MediaType.APPLICATION_JSON).content(body))
				.andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
		Long id = om.readTree(res).at("/data/id").asLong();

		try {
			// On-duty cannot delete
			mvc.perform(delete("/api/v1/auto-patrols/" + id).header("Authorization", "Bearer " + onDutyToken))
					.andExpect(status().isForbidden());
			// PE can delete (Phase 3 chose PE or IT_ADMIN for patrol lifecycle)
			mvc.perform(delete("/api/v1/auto-patrols/" + id).header("Authorization", "Bearer " + peToken))
					.andExpect(status().isOk());
			assertThat(patrolRepo.findById(id)).isEmpty();
		} finally {
			patrolRepo.findById(id).ifPresent(patrolRepo::delete);
		}
	}
}
