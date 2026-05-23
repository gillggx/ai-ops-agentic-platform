package com.aiops.api.domain;

import com.aiops.api.domain.agent.*;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.domain.event.*;
import com.aiops.api.domain.mcp.*;
import com.aiops.api.domain.patrol.AutoPatrolRepository;
import com.aiops.api.domain.pipeline.*;
import com.aiops.api.domain.skill.*;
import com.aiops.api.domain.system.SystemParameterRepository;
import com.aiops.api.domain.user.*;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.test.context.ActiveProfiles;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Smoke Test — exercises every live repository with a basic count() query
 * to prove the full JPA stack (entity mapping → Hibernate → Postgres) works
 * end-to-end for all domain entities.
 *
 * <p>2026-05-23: trimmed from 29 → 23 repos after dead-code purge removed
 * DataSubject / MockDataSource / ScriptVersion / CronJob / AgentMemory /
 * AgentExperienceMemory entities.
 */
@SpringBootTest
@ActiveProfiles("test")
class RepositorySmokeTest {

	// --- user/ ---
	@Autowired UserRepository userRepo;
	@Autowired UserPreferenceRepository userPreferenceRepo;
	@Autowired ItemRepository itemRepo;
	// --- event/ ---
	@Autowired EventTypeRepository eventTypeRepo;
	@Autowired GeneratedEventRepository generatedEventRepo;
	@Autowired NatsEventLogRepository natsEventLogRepo;
	// --- mcp/ ---
	@Autowired McpDefinitionRepository mcpDefinitionRepo;
	// --- alarm/ ---
	@Autowired AlarmRepository alarmRepo;
	// --- skill/ ---
	@Autowired SkillDefinitionRepository skillRepo;
	@Autowired RoutineCheckRepository routineCheckRepo;
	@Autowired ExecutionLogRepository executionLogRepo;
	@Autowired FeedbackLogRepository feedbackLogRepo;
	// --- agent/ ---
	@Autowired AgentDraftRepository agentDraftRepo;
	@Autowired AgentSessionRepository agentSessionRepo;
	@Autowired AgentToolRepository agentToolRepo;
	// --- pipeline/ ---
	@Autowired BlockRepository blockRepo;
	@Autowired PipelineRepository pipelineRepo;
	@Autowired PipelineRunRepository pipelineRunRepo;
	@Autowired CanvasOperationRepository canvasOperationRepo;
	@Autowired PublishedSkillRepository publishedSkillRepo;
	@Autowired PipelineAutoCheckTriggerRepository pipelineAutoCheckRepo;
	// --- patrol/ ---
	@Autowired AutoPatrolRepository autoPatrolRepo;
	// --- system/ ---
	@Autowired SystemParameterRepository systemParameterRepo;

	@Test
	@DisplayName("All live repositories are wired and can query their table")
	void allLiveRepositoriesCanCount() {
		List<JpaRepository<?, ?>> all = List.of(
				userRepo, userPreferenceRepo, itemRepo,
				eventTypeRepo, generatedEventRepo, natsEventLogRepo,
				mcpDefinitionRepo,
				alarmRepo,
				skillRepo, routineCheckRepo, executionLogRepo, feedbackLogRepo,
				agentDraftRepo, agentSessionRepo, agentToolRepo,
				blockRepo, pipelineRepo, pipelineRunRepo, canvasOperationRepo, publishedSkillRepo, pipelineAutoCheckRepo,
				autoPatrolRepo,
				systemParameterRepo);

		assertThat(all).hasSize(23);
		for (JpaRepository<?, ?> r : all) {
			long count = r.count();
			assertThat(count).isGreaterThanOrEqualTo(0L);
		}
	}
}
