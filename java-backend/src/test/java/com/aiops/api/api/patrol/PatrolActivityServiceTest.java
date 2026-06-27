package com.aiops.api.api.patrol;

import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.domain.event.GeneratedEventRepository;
import com.aiops.api.domain.skill.SkillDocumentEntity;
import com.aiops.api.domain.skill.SkillDocumentRepository;
import com.aiops.api.domain.skill.SkillRunEntity;
import com.aiops.api.domain.skill.SkillRunRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

/**
 * Pure-Mockito coverage for the Patrol Activity assembly logic. No Spring
 * context — the service is a thin orchestrator over four repositories and
 * one ObjectMapper, so each scenario gets stubbed inputs and asserts on
 * the response shape.
 *
 * <p>Pattern lifted from {@code SkillAlarmEmitterTest}: use lenient stubs
 * (UNNECESSARY_STUBS warning would otherwise mask wiring bugs across
 * branches that aren't hit in every test).
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class PatrolActivityServiceTest {

	private static final OffsetDateTime SINCE = OffsetDateTime.of(2026, 6, 27, 6, 0, 0, 0, ZoneOffset.UTC);
	private static final OffsetDateTime UNTIL = OffsetDateTime.of(2026, 6, 27, 7, 0, 0, 0, ZoneOffset.UTC);

	@Mock private SkillRunRepository runRepo;
	@Mock private SkillDocumentRepository skillRepo;
	@Mock private AlarmRepository alarmRepo;
	@Mock private GeneratedEventRepository eventRepo;

	private ObjectMapper mapper;
	private PatrolActivityService service;

	@BeforeEach
	void setUp() {
		mapper = new ObjectMapper();
		service = new PatrolActivityService(runRepo, skillRepo, alarmRepo, eventRepo, mapper);

		// Default funnel stubs — each test overrides as needed.
		when(eventRepo.countByCreatedAtBetween(any(), any())).thenReturn(126L);
		when(runRepo.countByTriggeredAtBetween(any(), any())).thenReturn(308L);
		when(runRepo.countByTriggeredAtBetweenAndStepPassed(any(), any())).thenReturn(94L);
		when(alarmRepo.countByCreatedAtBetween(any(), any())).thenReturn(7L);
		when(runRepo.countByTriggeredAtBetweenAndAlarmSkippedReason(any(), any(), eq("dedup")))
				.thenReturn(2L);
	}

	private PatrolActivityService.Query baseQuery() {
		return new PatrolActivityService.Query(SINCE, UNTIL, null, null, null, null, 100, null);
	}

	@Test
	void emptyRuns_returnsFunnelOnlyWithEmptyItems() {
		when(runRepo.findActivity(any(), any(), any(), any(), anyInt())).thenReturn(List.of());

		var resp = service.queryActivity(baseQuery());

		assertThat(resp.items()).isEmpty();
		assertThat(resp.nextCursor()).isNull();
		assertThat(resp.funnel().events()).isEqualTo(126L);
		assertThat(resp.funnel().skillRuns()).isEqualTo(308L);
		assertThat(resp.funnel().stepPassed()).isEqualTo(94L);
		assertThat(resp.funnel().alarms()).isEqualTo(7L);
		assertThat(resp.funnel().dedupSuppressed()).isEqualTo(2L);
	}

	@Test
	void singleRun_extractsEventFieldsFromTriggerPayload() {
		SkillRunEntity run = makeRun(8842L, 115L,
				"{\"equipment_id\":\"EQP-10\",\"lot_id\":\"LOT-2571\",\"step_id\":\"STEP_015\","
						+ "\"event_time\":\"2026-06-27T07:05:14Z\"}",
				"{\"steps\":[{\"step_id\":\"s1\",\"status\":\"pass\"},"
						+ "{\"step_id\":\"s2\",\"status\":\"fail\"}]}",
				null);
		SkillDocumentEntity skill = makeSkill(115L, "ooc-diag", "OOC Diagnose", "diagnose",
				"{\"type\":\"event\",\"event\":\"OOC\"}");

		when(runRepo.findActivity(any(), any(), any(), any(), anyInt()))
				.thenReturn(List.of(run));
		when(skillRepo.findAllById(any())).thenReturn(List.of(skill));
		when(alarmRepo.findBySkillRunIdIn(any())).thenReturn(List.of());

		var resp = service.queryActivity(baseQuery());

		assertThat(resp.items()).hasSize(1);
		var item = resp.items().get(0);
		assertThat(item.skillRunId()).isEqualTo(8842L);
		assertThat(item.skillSlug()).isEqualTo("ooc-diag");
		assertThat(item.skillStage()).isEqualTo("diagnose");
		assertThat(item.equipmentId()).isEqualTo("EQP-10");
		assertThat(item.lotId()).isEqualTo("LOT-2571");
		assertThat(item.stepId()).isEqualTo("STEP_015");
		assertThat(item.eventType()).isEqualTo("OOC");
		assertThat(item.stepsTotal()).isEqualTo(2);
		assertThat(item.stepsPassed()).isEqualTo(1);
		assertThat(item.alarmId()).isNull();
	}

	@Test
	void runWithAlarm_setsAlarmIdAndIgnoresSkippedReason() {
		SkillRunEntity run = makeRun(100L, 43L, "{}",
				"{\"steps\":[{\"status\":\"pass\"}]}", null);
		SkillDocumentEntity skill = makeSkill(43L, "patrol-skill", "Patrol", "patrol",
				"{\"type\":\"event\",\"event\":\"OOC\"}");
		AlarmEntity alarm = new AlarmEntity();
		alarm.setId(555L);
		alarm.setSkillRunId(100L);

		when(runRepo.findActivity(any(), any(), any(), any(), anyInt()))
				.thenReturn(List.of(run));
		when(skillRepo.findAllById(any())).thenReturn(List.of(skill));
		when(alarmRepo.findBySkillRunIdIn(any())).thenReturn(List.of(alarm));

		var resp = service.queryActivity(baseQuery());

		assertThat(resp.items()).hasSize(1);
		assertThat(resp.items().get(0).alarmId()).isEqualTo(555L);
	}

	@Test
	void eventTypeFilter_dropsRunsThatDontMatch() {
		SkillRunEntity oocRun = makeRun(1L, 11L, "{}", "{}", null);
		SkillRunEntity hourlyRun = makeRun(2L, 22L, "{}", "{}", null);
		SkillDocumentEntity oocSkill = makeSkill(11L, "ooc", "OOC", "diagnose",
				"{\"type\":\"event\",\"event\":\"OOC\"}");
		SkillDocumentEntity hourlySkill = makeSkill(22L, "hourly", "Hourly", "patrol",
				"{\"type\":\"schedule\",\"schedule\":{\"mode\":\"hourly\"}}");

		when(runRepo.findActivity(any(), any(), any(), any(), anyInt()))
				.thenReturn(List.of(oocRun, hourlyRun));
		when(skillRepo.findAllById(any())).thenReturn(List.of(oocSkill, hourlySkill));
		when(alarmRepo.findBySkillRunIdIn(any())).thenReturn(List.of());

		var q = new PatrolActivityService.Query(SINCE, UNTIL, "OOC", null, null, null, 100, null);
		var resp = service.queryActivity(q);

		assertThat(resp.items()).hasSize(1);
		assertThat(resp.items().get(0).skillRunId()).isEqualTo(1L);
	}

	@Test
	void outcomeFilter_alarm_emitted_keepsOnlyRunsWithAlarmId() {
		SkillRunEntity r1 = makeRun(1L, 10L, "{}", "{\"steps\":[{\"status\":\"pass\"}]}", null);
		SkillRunEntity r2 = makeRun(2L, 10L, "{}", "{\"steps\":[{\"status\":\"fail\"}]}", "no_step_passed");
		SkillDocumentEntity skill = makeSkill(10L, "s", "S", "patrol",
				"{\"type\":\"event\",\"event\":\"OOC\"}");
		AlarmEntity alarm = new AlarmEntity();
		alarm.setId(777L);
		alarm.setSkillRunId(1L);

		when(runRepo.findActivity(any(), any(), any(), any(), anyInt()))
				.thenReturn(List.of(r1, r2));
		when(skillRepo.findAllById(any())).thenReturn(List.of(skill));
		when(alarmRepo.findBySkillRunIdIn(any())).thenReturn(List.of(alarm));

		var q = new PatrolActivityService.Query(SINCE, UNTIL, null, null, null, "alarm_emitted", 100, null);
		var resp = service.queryActivity(q);

		assertThat(resp.items()).extracting(PatrolActivityService.Item::skillRunId)
				.containsExactly(1L);
	}

	@Test
	void hasMoreRuns_setsNextCursorToLastSeenId() {
		// Service asks for limit+1; we return exactly limit+1 to trigger has-more.
		SkillRunEntity r1 = makeRun(10L, 1L, "{}", "{}", null);
		SkillRunEntity r2 = makeRun(9L, 1L, "{}", "{}", null);  // older, sort DESC
		SkillRunEntity r3 = makeRun(8L, 1L, "{}", "{}", null);
		SkillDocumentEntity skill = makeSkill(1L, "s", "S", "patrol",
				"{\"type\":\"event\",\"event\":\"OOC\"}");

		when(runRepo.findActivity(any(), any(), any(), any(), anyInt()))
				.thenReturn(List.of(r1, r2, r3));
		when(skillRepo.findAllById(any())).thenReturn(List.of(skill));
		when(alarmRepo.findBySkillRunIdIn(any())).thenReturn(List.of());

		var q = new PatrolActivityService.Query(SINCE, UNTIL, null, null, null, null, 2, null);
		var resp = service.queryActivity(q);

		// Service truncates to limit (2) and emits nextCursor = id of last KEPT row.
		assertThat(resp.items()).hasSize(2);
		assertThat(resp.nextCursor()).isEqualTo(9L);
	}

	@Test
	void skillNotFound_itemStillEmittedWithNullSkillFields() {
		// Defensive: if a stale skill_run row references a deleted skill,
		// the page should still render rather than 500ing.
		SkillRunEntity run = makeRun(1L, 999L, "{}", "{}", null);

		when(runRepo.findActivity(any(), any(), any(), any(), anyInt()))
				.thenReturn(List.of(run));
		when(skillRepo.findAllById(any())).thenReturn(List.of());  // skill 999 not found
		when(alarmRepo.findBySkillRunIdIn(any())).thenReturn(List.of());

		var resp = service.queryActivity(baseQuery());

		assertThat(resp.items()).hasSize(1);
		var item = resp.items().get(0);
		assertThat(item.skillSlug()).isNull();
		assertThat(item.skillStage()).isNull();
		assertThat(item.eventType()).isNull();
	}

	@Test
	void payload_supportsLegacyKeyAliases() {
		// lot_id / lotID, equipment_id / tool_id, step_id / step — both should
		// resolve. Older simulator payloads use camelCase aliases.
		SkillRunEntity run = makeRun(1L, 1L,
				"{\"tool_id\":\"EQP-99\",\"lotID\":\"LOT-X\",\"step\":\"STEP_007\"}",
				"{}", null);
		SkillDocumentEntity skill = makeSkill(1L, "s", "S", "patrol",
				"{\"type\":\"event\",\"event\":\"OOC\"}");

		when(runRepo.findActivity(any(), any(), any(), any(), anyInt()))
				.thenReturn(List.of(run));
		when(skillRepo.findAllById(any())).thenReturn(List.of(skill));
		when(alarmRepo.findBySkillRunIdIn(any())).thenReturn(List.of());

		var item = service.queryActivity(baseQuery()).items().get(0);

		assertThat(item.equipmentId()).isEqualTo("EQP-99");
		assertThat(item.lotId()).isEqualTo("LOT-X");
		assertThat(item.stepId()).isEqualTo("STEP_007");
	}

	// ─── helpers ────────────────────────────────────────────────────────

	private SkillRunEntity makeRun(Long id, Long skillId, String payload, String stepResults,
	                               String alarmSkippedReason) {
		SkillRunEntity r = new SkillRunEntity();
		r.setId(id);
		r.setSkillId(skillId);
		r.setTriggeredAt(SINCE.plusMinutes(30));
		r.setTriggeredBy("system_event");
		r.setTriggerPayload(payload);
		r.setStepResults(stepResults);
		r.setStatus("completed");
		r.setDurationMs(120);
		r.setAlarmSkippedReason(alarmSkippedReason);
		return r;
	}

	private SkillDocumentEntity makeSkill(Long id, String slug, String title, String stage,
	                                       String triggerConfig) {
		SkillDocumentEntity s = new SkillDocumentEntity();
		s.setId(id);
		s.setSlug(slug);
		s.setTitle(title);
		s.setStage(stage);
		s.setTriggerConfig(triggerConfig);
		return s;
	}

	private static int anyInt() {
		return org.mockito.ArgumentMatchers.anyInt();
	}
}
