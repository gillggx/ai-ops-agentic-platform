package com.aiops.api.api;

import com.aiops.api.auth.Role;
import com.aiops.api.auth.UserAccountService;
import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.domain.event.EventTypeRepository;
import com.aiops.api.domain.system.SystemParameterRepository;
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

/**
 * Phase 3a — Alarm + EventType + SystemParameter CRUD with role gating.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class Phase3aIntegrationTest {

	@Autowired MockMvc mvc;
	@Autowired UserRepository userRepo;
	@Autowired UserAccountService userAccountService;
	@Autowired AlarmRepository alarmRepo;
	@Autowired EventTypeRepository eventTypeRepo;
	@Autowired SystemParameterRepository systemParamRepo;
	@Autowired ObjectMapper om;

	private String adminToken;
	private String peToken;
	private String onDutyToken;

	@BeforeEach
	void setup() throws Exception {
		// Leave admin seeded by BootstrapSeeder; create PE + On-duty if absent.
		if (!userRepo.existsByUsername("pe_phase3")) {
			userAccountService.createUser("pe_phase3", "pe3@x.com", "pe_pw", EnumSet.of(Role.PE));
		}
		if (!userRepo.existsByUsername("on_duty_phase3")) {
			userAccountService.createUser("on_duty_phase3", "od3@x.com", "od_pw", EnumSet.of(Role.ON_DUTY));
		}
		adminToken = loginToken("admin", "admin");
		peToken = loginToken("pe_phase3", "pe_pw");
		onDutyToken = loginToken("on_duty_phase3", "od_pw");
	}

	private String loginToken(String user, String pass) throws Exception {
		String body = mvc.perform(post("/api/v1/auth/login")
						.contentType(MediaType.APPLICATION_JSON)
						.content("{\"username\":\"" + user + "\",\"password\":\"" + pass + "\"}"))
				.andExpect(status().isOk())
				.andReturn().getResponse().getContentAsString();
		JsonNode node = om.readTree(body);
		return node.at("/data/access_token").asText();
	}

	// --- Alarms ---

	@Test
	void alarmAckFlow() throws Exception {
		AlarmEntity a = new AlarmEntity();
		a.setSkillId(1L);
		a.setTitle("phase3a test");
		a.setSeverity("HIGH");
		a.setStatus("active");
		a = alarmRepo.save(a);
		Long id = a.getId();

		try {
			// On-duty can list + ack
			mvc.perform(get("/api/v1/alarms").header("Authorization", "Bearer " + onDutyToken))
					.andExpect(status().isOk())
					.andExpect(jsonPath("$.ok").value(true));

			mvc.perform(post("/api/v1/alarms/" + id + "/ack")
							.header("Authorization", "Bearer " + onDutyToken))
					.andExpect(status().isOk())
					.andExpect(jsonPath("$.data.status").value("acknowledged"))
					.andExpect(jsonPath("$.data.acknowledged_by").value("on_duty_phase3"));

			// On-duty CANNOT resolve
			mvc.perform(post("/api/v1/alarms/" + id + "/resolve")
							.header("Authorization", "Bearer " + onDutyToken))
					.andExpect(status().isForbidden());

			// PE can resolve
			mvc.perform(post("/api/v1/alarms/" + id + "/resolve")
							.header("Authorization", "Bearer " + peToken))
					.andExpect(status().isOk())
					.andExpect(jsonPath("$.data.status").value("resolved"));
		} finally {
			alarmRepo.deleteById(id);
		}
	}

	// --- EventType ---

	@Test
	void eventTypeCrudRespectsRoles() throws Exception {
		String name = "phase3a_event_" + System.nanoTime();
		String createBody = "{\"name\":\"" + name + "\",\"description\":\"hello\"}";

		// On-duty cannot create
		mvc.perform(post("/api/v1/event-types")
						.header("Authorization", "Bearer " + onDutyToken)
						.contentType(MediaType.APPLICATION_JSON)
						.content(createBody))
				.andExpect(status().isForbidden());

		// PE can create
		String res = mvc.perform(post("/api/v1/event-types")
						.header("Authorization", "Bearer " + peToken)
						.contentType(MediaType.APPLICATION_JSON)
						.content(createBody))
				.andExpect(status().isOk())
				.andReturn().getResponse().getContentAsString();
		Long id = om.readTree(res).at("/data/id").asLong();
		assertThat(id).isPositive();

		try {
			// All three roles can read
			mvc.perform(get("/api/v1/event-types/" + id)
							.header("Authorization", "Bearer " + onDutyToken))
					.andExpect(status().isOk());

			// Only IT_ADMIN can delete
			mvc.perform(delete("/api/v1/event-types/" + id)
							.header("Authorization", "Bearer " + peToken))
					.andExpect(status().isForbidden());

			mvc.perform(delete("/api/v1/event-types/" + id)
							.header("Authorization", "Bearer " + adminToken))
					.andExpect(status().isOk());
			assertThat(eventTypeRepo.findById(id)).isEmpty();
		} finally {
			eventTypeRepo.findById(id).ifPresent(eventTypeRepo::delete);
		}
	}

	// --- SystemParameter ---

	@Test
	void systemParameterWritesRequireAdmin() throws Exception {
		String key = "phase3a.test." + System.nanoTime();
		String body = "{\"value\":\"hello\",\"description\":\"smoke\"}";

		// PE cannot write
		mvc.perform(put("/api/v1/system-parameters/" + key)
						.header("Authorization", "Bearer " + peToken)
						.contentType(MediaType.APPLICATION_JSON)
						.content(body))
				.andExpect(status().isForbidden());

		// Admin can
		mvc.perform(put("/api/v1/system-parameters/" + key)
						.header("Authorization", "Bearer " + adminToken)
						.contentType(MediaType.APPLICATION_JSON)
						.content(body))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.data.value").value("hello"));

		try {
			// All roles can read
			mvc.perform(get("/api/v1/system-parameters/" + key)
							.header("Authorization", "Bearer " + onDutyToken))
					.andExpect(status().isOk())
					.andExpect(jsonPath("$.data.value").value("hello"));
		} finally {
			systemParamRepo.findByKey(key).ifPresent(systemParamRepo::delete);
		}
	}
}
