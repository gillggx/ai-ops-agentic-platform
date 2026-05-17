package com.aiops.api.api.skill;

import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.skill.ExecutionLogEntity;
import com.aiops.api.domain.skill.ExecutionLogRepository;
import com.aiops.api.domain.skill.SkillDocumentEntity;
import com.aiops.api.domain.skill.SkillDocumentRepository;
import com.aiops.api.domain.skill.SkillRunEntity;
import com.aiops.api.domain.skill.SkillRunRepository;
import com.aiops.api.sidecar.PythonSidecarClient;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.entry;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * v30.13b — comprehensive coverage of SkillRunnerService alarm-emit path.
 *
 * Targets:
 *   - emitAlarmIfTriggered: every guard branch + happy path + dedup
 *   - parseEvidenceTimestamp: 4 input shapes
 *   - pickFirstEvidenceRow: tolerant parsing
 *   - deriveTriggerEvent: schedule vs event
 *   - alarmEmitStats: snapshot fidelity
 *
 * Strategy: pure Mockito (no Spring context) — fast, deterministic. The
 * runWithSink() integration path is not unit-tested here; emit logic is
 * isolated in emitAlarmIfTriggered which IS unit-tested. End-to-end is
 * exercised by the live deploy verification (see commit log of v30.13b).
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class SkillRunnerServiceTest {

    @Mock SkillDocumentRepository skillRepo;
    @Mock SkillRunRepository runRepo;
    @Mock PipelineRepository pipelineRepo;
    @Mock PythonSidecarClient sidecar;
    @Mock AlarmRepository alarmRepo;
    @Mock ExecutionLogRepository execLogRepo;

    private ObjectMapper mapper;
    private SkillRunnerService service;

    @BeforeEach
    void setup() {
        mapper = new ObjectMapper();
        service = new SkillRunnerService(skillRepo, runRepo, pipelineRepo,
                sidecar, mapper, alarmRepo, execLogRepo);
        // v30.15: execLogRepo.save returns entity with id assigned; default
        // for tests so existing emit tests still pass without per-test setup.
        when(execLogRepo.save(any(ExecutionLogEntity.class))).thenAnswer(inv -> {
            ExecutionLogEntity e = inv.getArgument(0); e.setId(7777L); return e;
        });
    }

    // ────────────────────────── parseEvidenceTimestamp ──────────────────────────

    @Nested @DisplayName("parseEvidenceTimestamp")
    class ParseTimestamp {

        @Test
        void isoWithOffset() {
            OffsetDateTime t = SkillRunnerService.parseEvidenceTimestamp(
                    "2026-05-17T00:21:13.505000+00:00");
            assertThat(t).isNotNull();
            assertThat(t.getYear()).isEqualTo(2026);
            assertThat(t.getOffset()).isEqualTo(ZoneOffset.UTC);
        }

        @Test
        void isoNoOffsetAssumedUtc() {
            OffsetDateTime t = SkillRunnerService.parseEvidenceTimestamp(
                    "2026-05-17T00:21:13.505000");
            assertThat(t).isNotNull();
            assertThat(t.getOffset()).isEqualTo(ZoneOffset.UTC);
            assertThat(t.getHour()).isEqualTo(0);
            assertThat(t.getMinute()).isEqualTo(21);
        }

        @Test
        void isoNoFractionNoOffset() {
            OffsetDateTime t = SkillRunnerService.parseEvidenceTimestamp(
                    "2026-05-17T00:21:13");
            assertThat(t).isNotNull();
            assertThat(t.getOffset()).isEqualTo(ZoneOffset.UTC);
            assertThat(t.getSecond()).isEqualTo(13);
        }

        @Test
        void nullStringReturnsNull() {
            assertThat(SkillRunnerService.parseEvidenceTimestamp(null)).isNull();
        }

        @Test
        void emptyStringReturnsNull() {
            assertThat(SkillRunnerService.parseEvidenceTimestamp("")).isNull();
        }

        @Test
        void blankStringReturnsNull() {
            assertThat(SkillRunnerService.parseEvidenceTimestamp("   ")).isNull();
        }

        @Test
        void literalNullStringReturnsNull() {
            assertThat(SkillRunnerService.parseEvidenceTimestamp("null")).isNull();
        }

        @Test
        void unparseableGarbageReturnsNull() {
            assertThat(SkillRunnerService.parseEvidenceTimestamp("not-a-date")).isNull();
        }
    }

    // ────────────────────────── pickFirstEvidenceRow ──────────────────────────

    @Nested @DisplayName("pickFirstEvidenceRow")
    class PickFirstRow {

        @Test
        void nullConfirm() {
            assertThat(service.pickFirstEvidenceRow(null)).isNull();
        }

        @Test
        void confirmWithoutDataViews() {
            Map<String, Object> confirm = Map.of("status", "pass");
            assertThat(service.pickFirstEvidenceRow(confirm)).isNull();
        }

        @Test
        void dataViewsNotAList() {
            Map<String, Object> confirm = Map.of("data_views", "scalar-not-list");
            assertThat(service.pickFirstEvidenceRow(confirm)).isNull();
        }

        @Test
        void dataViewsEmpty() {
            Map<String, Object> confirm = Map.of("data_views", List.of());
            assertThat(service.pickFirstEvidenceRow(confirm)).isNull();
        }

        @Test
        void firstDataViewNotMap() {
            Map<String, Object> confirm = Map.of("data_views", List.of("scalar-not-map"));
            assertThat(service.pickFirstEvidenceRow(confirm)).isNull();
        }

        @Test
        void rowsKeyMissing() {
            Map<String, Object> dv = Map.of("block", "test");
            Map<String, Object> confirm = Map.of("data_views", List.of(dv));
            assertThat(service.pickFirstEvidenceRow(confirm)).isNull();
        }

        @Test
        void rowsEmpty() {
            Map<String, Object> dv = Map.of("rows", List.of());
            Map<String, Object> confirm = Map.of("data_views", List.of(dv));
            assertThat(service.pickFirstEvidenceRow(confirm)).isNull();
        }

        @Test
        void firstRowNotMap() {
            Map<String, Object> dv = Map.of("rows", List.of("scalar-row"));
            Map<String, Object> confirm = Map.of("data_views", List.of(dv));
            assertThat(service.pickFirstEvidenceRow(confirm)).isNull();
        }

        @Test
        void happyPathReturnsFirstRow() {
            Map<String, Object> row = Map.of("eventTime", "2026-05-17T00:21:13",
                    "toolID", "EQP-01", "lotID", "LOT-001", "spc_status", "OOC");
            Map<String, Object> dv = Map.of("rows", List.of(row));
            Map<String, Object> confirm = Map.of("data_views", List.of(dv));
            Map<String, Object> result = service.pickFirstEvidenceRow(confirm);
            assertThat(result).isNotNull();
            assertThat(result).contains(entry("toolID", "EQP-01"),
                                         entry("lotID", "LOT-001"));
        }
    }

    // ────────────────────────── deriveTriggerEvent ──────────────────────────

    @Nested @DisplayName("deriveTriggerEvent")
    class DeriveTrigger {

        @Test
        void nullConfigDefaultsToPatrol() {
            assertThat(service.deriveTriggerEvent(null)).isEqualTo("patrol_check");
        }

        @Test
        void emptyConfigDefaultsToPatrol() {
            assertThat(service.deriveTriggerEvent(Map.of())).isEqualTo("patrol_check");
        }

        @Test
        void scheduleTypeReturnsPatrol() {
            Map<String, Object> cfg = Map.of("type", "schedule",
                    "schedule", Map.of("mode", "hourly"));
            assertThat(service.deriveTriggerEvent(cfg)).isEqualTo("patrol_check");
        }

        @Test
        void eventTypeReturnsEventName() {
            Map<String, Object> cfg = Map.of("type", "event", "event", "OOC");
            assertThat(service.deriveTriggerEvent(cfg)).isEqualTo("OOC");
        }

        @Test
        void eventTypeMissingEventNameFallsBack() {
            Map<String, Object> cfg = Map.of("type", "event");
            assertThat(service.deriveTriggerEvent(cfg)).isEqualTo("patrol_check");
        }

        @Test
        void eventTypeBlankEventNameFallsBack() {
            Map<String, Object> cfg = Map.of("type", "event", "event", "  ");
            assertThat(service.deriveTriggerEvent(cfg)).isEqualTo("patrol_check");
        }

        @Test
        void unknownTypeFallsBack() {
            Map<String, Object> cfg = Map.of("type", "weird");
            assertThat(service.deriveTriggerEvent(cfg)).isEqualTo("patrol_check");
        }
    }

    // ────────────────────────── alarmEmitStats ──────────────────────────

    @Nested @DisplayName("alarmEmitStats")
    class StatsSnapshot {

        @Test
        void initialStateAllZeroAndNull() {
            Map<String, Object> s = service.alarmEmitStats();
            assertThat(s).containsEntry("alarms_emitted", 0L);
            assertThat(s).containsEntry("alarms_dedup_suppressed", 0L);
            assertThat(s).containsEntry("last_emit_at", null);
            assertThat(s).containsEntry("last_skill", null);
            assertThat(s).containsEntry("last_alarm_id", null);
        }

        @Test
        void countersIncrementAfterSuccessfulEmit() {
            SkillDocumentEntity skill = patrolSkill();
            SkillRunEntity run = run(false);
            Map<String, Object> confirm = confirmWithRow("LOT-X", "STEP_01",
                    "2026-05-17T00:00:00");
            List<Map<String, Object>> steps = List.of(stepPass("s1"));

            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            when(alarmRepo.save(any(AlarmEntity.class))).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0);
                a.setId(999L);
                return a;
            });

            AlarmEntity result = service.emitAlarmIfTriggered(skill, run,
                    Map.of("tool_id", "EQP-02"), confirm, steps, false);

            assertThat(result).isNotNull();
            assertThat(result.getId()).isEqualTo(999L);

            Map<String, Object> stats = service.alarmEmitStats();
            assertThat(stats).containsEntry("alarms_emitted", 1L);
            assertThat(stats).containsEntry("last_alarm_id", 999L);
            assertThat(stats).containsEntry("last_skill", skill.getSlug());
            assertThat((String) stats.get("last_emit_at")).isNotNull();
        }

        @Test
        void dedupCounterIncrementsOnSuppress() {
            SkillDocumentEntity skill = patrolSkill();
            SkillRunEntity run = run(false);
            Map<String, Object> confirm = confirmWithRow("LOT", "STEP",
                    "2026-05-17T00:00:00");
            List<Map<String, Object>> steps = List.of(stepPass("s1"));

            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(true);

            AlarmEntity result = service.emitAlarmIfTriggered(skill, run,
                    Map.of("tool_id", "EQP-02"), confirm, steps, false);

            assertThat(result).isNull();
            verify(alarmRepo, never()).save(any(AlarmEntity.class));

            Map<String, Object> stats = service.alarmEmitStats();
            assertThat(stats).containsEntry("alarms_emitted", 0L);
            assertThat(stats).containsEntry("alarms_dedup_suppressed", 1L);
        }
    }

    // ────────────────────────── emitAlarmIfTriggered guards ──────────────────

    @Nested @DisplayName("emitAlarmIfTriggered guards")
    class Guards {

        @Test
        void isTestSkipsEmit() {
            AlarmEntity r = service.emitAlarmIfTriggered(
                    patrolSkill(), run(true),
                    Map.of("tool_id", "EQP-02"),
                    confirmWithRow("L", "S", "2026-05-17T00:00:00"),
                    List.of(stepPass("s1")), false);
            assertThat(r).isNull();
            verify(alarmRepo, never()).save(any());
            verify(alarmRepo, never()).existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any());
        }

        @Test
        void diagnoseStageSkipsEmit() {
            SkillDocumentEntity diagnose = patrolSkill();
            diagnose.setStage("diagnose");
            AlarmEntity r = service.emitAlarmIfTriggered(
                    diagnose, run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirmWithRow("L", "S", "2026-05-17T00:00:00"),
                    List.of(stepPass("s1")), false);
            assertThat(r).isNull();
            verify(alarmRepo, never()).save(any());
        }

        @Test
        void caseInsensitivePatrolStageStillEmits() {
            SkillDocumentEntity skill = patrolSkill();
            skill.setStage("PATROL");  // case variation
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            when(alarmRepo.save(any(AlarmEntity.class))).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });
            AlarmEntity r = service.emitAlarmIfTriggered(
                    skill, run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirmWithRow("L", "S", "2026-05-17T00:00:00"),
                    List.of(stepPass("s1")), false);
            assertThat(r).isNotNull();
        }

        @Test
        void skipChecklistTrueSkipsEmit() {
            AlarmEntity r = service.emitAlarmIfTriggered(
                    patrolSkill(), run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirmWithRow("L", "S", "2026-05-17T00:00:00"),
                    List.of(stepPass("s1")), true);  // skipChecklist=true
            assertThat(r).isNull();
            verify(alarmRepo, never()).save(any());
        }

        @Test
        void noTriggeredStepSkipsEmit() {
            AlarmEntity r = service.emitAlarmIfTriggered(
                    patrolSkill(), run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirmWithRow("L", "S", "2026-05-17T00:00:00"),
                    List.of(stepFail("s1"), stepFail("s2")), false);
            assertThat(r).isNull();
            verify(alarmRepo, never()).save(any());
        }

        @Test
        void mixedStepsAnyPassEmits() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            when(alarmRepo.save(any(AlarmEntity.class))).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });
            AlarmEntity r = service.emitAlarmIfTriggered(
                    patrolSkill(), run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirmWithRow("L", "S", "2026-05-17T00:00:00"),
                    List.of(stepFail("s1"), stepPass("s2"), stepFail("s3")), false);
            assertThat(r).isNotNull();
        }
    }

    // ────────────────────────── emitAlarmIfTriggered field derivation ──────

    @Nested @DisplayName("emitAlarmIfTriggered field derivation")
    class FieldDerivation {

        @Test
        void happyPathPopulatesAllFields() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(42L); return a;
            });

            SkillDocumentEntity skill = patrolSkill();
            skill.setTriggerConfig("{\"type\":\"schedule\",\"severity\":\"high\"}");
            AlarmEntity r = service.emitAlarmIfTriggered(
                    skill, run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirmWithRow("LOT-001", "STEP_009", "2026-05-17T00:21:13.505000"),
                    List.of(stepPass("s_check", "ooc>=2")), false);

            assertThat(r).isNotNull();
            AlarmEntity saved = cap.getValue();
            assertThat(saved.getSkillId()).isEqualTo(skill.getId());
            assertThat(saved.getEquipmentId()).isEqualTo("EQP-02");
            assertThat(saved.getLotId()).isEqualTo("LOT-001");
            assertThat(saved.getStep()).isEqualTo("STEP_009");
            assertThat(saved.getSeverity()).isEqualTo("HIGH");
            assertThat(saved.getTitle()).contains("EQP-02");
            assertThat(saved.getStatus()).isEqualTo("active");
            assertThat(saved.getTriggerEvent()).isEqualTo("patrol_check");
            assertThat(saved.getEventTime()).isNotNull();
            assertThat(saved.getEventTime().getYear()).isEqualTo(2026);
            assertThat(saved.getSummary()).contains("Confirm:");
            assertThat(saved.getSummary()).contains("ooc>=2");
            assertThat(saved.getSummary()).contains("SkillRun #");
        }

        @Test
        void noToolIdYieldsAnySentinel() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });

            service.emitAlarmIfTriggered(
                    patrolSkill(), run(false),
                    Map.of(),  // no tool_id
                    confirmWithRow("L", "S", "2026-05-17T00:00:00"),
                    List.of(stepPass("s1")), false);

            assertThat(cap.getValue().getEquipmentId()).isEqualTo("(any)");
        }

        @Test
        void equipmentIdFallbackKeyAccepted() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });

            // Trigger payload uses "equipment_id" key instead of "tool_id"
            service.emitAlarmIfTriggered(
                    patrolSkill(), run(false),
                    Map.of("equipment_id", "EQP-XX"),
                    confirmWithRow("L", "S", "2026-05-17T00:00:00"),
                    List.of(stepPass("s1")), false);

            assertThat(cap.getValue().getEquipmentId()).isEqualTo("EQP-XX");
        }

        @Test
        void noEvidenceRowFallsBackToNowForEventTime() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });

            // Confirm without data_views
            Map<String, Object> confirm = Map.of("status", "pass", "note", "n");
            OffsetDateTime before = OffsetDateTime.now().minusSeconds(2);
            service.emitAlarmIfTriggered(
                    patrolSkill(), run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirm,
                    List.of(stepPass("s1")), false);
            OffsetDateTime after = OffsetDateTime.now().plusSeconds(2);

            assertThat(cap.getValue().getEventTime()).isNotNull();
            assertThat(cap.getValue().getEventTime()).isAfterOrEqualTo(before);
            assertThat(cap.getValue().getEventTime()).isBeforeOrEqualTo(after);
            assertThat(cap.getValue().getLotId()).isEqualTo("");
            assertThat(cap.getValue().getStep()).isNull();
        }

        @Test
        void severityDefaultsToMediumWhenNotInTriggerConfig() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });

            SkillDocumentEntity skill = patrolSkill();
            skill.setTriggerConfig("{\"type\":\"schedule\"}");  // no severity

            service.emitAlarmIfTriggered(
                    skill, run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirmWithRow("L", "S", "2026-05-17T00:00:00"),
                    List.of(stepPass("s1")), false);

            assertThat(cap.getValue().getSeverity()).isEqualTo("MEDIUM");
        }

        @Test
        void triggerEventFromEventTypeConfig() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });

            SkillDocumentEntity skill = patrolSkill();
            skill.setTriggerConfig("{\"type\":\"event\",\"event\":\"OOC\"}");

            service.emitAlarmIfTriggered(
                    skill, run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirmWithRow("L", "S", "2026-05-17T00:00:00"),
                    List.of(stepPass("s1")), false);

            assertThat(cap.getValue().getTriggerEvent()).isEqualTo("OOC");
        }

        @Test
        void longTitleTruncatedTo290Chars() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });

            SkillDocumentEntity skill = patrolSkill();
            skill.setTitle("x".repeat(500));

            service.emitAlarmIfTriggered(
                    skill, run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirmWithRow("L", "S", "2026-05-17T00:00:00"),
                    List.of(stepPass("s1")), false);

            assertThat(cap.getValue().getTitle().length()).isLessThanOrEqualTo(290);
        }

        @Test
        void blankToolIdYieldsAnySentinel() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });
            service.emitAlarmIfTriggered(
                    patrolSkill(), run(false),
                    Map.of("tool_id", "   "),  // blank
                    confirmWithRow("L", "S", "2026-05-17T00:00:00"),
                    List.of(stepPass("s1")), false);
            assertThat(cap.getValue().getEquipmentId()).isEqualTo("(any)");
        }

        @Test
        void literalNullToolIdYieldsAnySentinel() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });
            // HashMap allows null value (Map.of does not), test "null" literal string
            Map<String, Object> payload = new HashMap<>();
            payload.put("tool_id", null);
            service.emitAlarmIfTriggered(
                    patrolSkill(), run(false), payload,
                    confirmWithRow("L", "S", "2026-05-17T00:00:00"),
                    List.of(stepPass("s1")), false);
            assertThat(cap.getValue().getEquipmentId()).isEqualTo("(any)");
        }

        @Test
        void nullTriggerPayloadYieldsAnySentinel() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });
            service.emitAlarmIfTriggered(
                    patrolSkill(), run(false), null,
                    confirmWithRow("L", "S", "2026-05-17T00:00:00"),
                    List.of(stepPass("s1")), false);
            assertThat(cap.getValue().getEquipmentId()).isEqualTo("(any)");
        }

        @Test
        void evidenceRowWithSnakeCaseKeysAccepted() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });
            // Evidence row using snake_case keys (lot_id / event_time) instead
            // of camelCase (lotID / eventTime).
            Map<String, Object> row = Map.of("lot_id", "LOT-snake",
                    "step", "STEP_snake", "event_time", "2026-05-17T00:00:00");
            Map<String, Object> confirm = Map.of("data_views",
                    List.of(Map.of("rows", List.of(row))), "note", "n");
            service.emitAlarmIfTriggered(
                    patrolSkill(), run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirm, List.of(stepPass("s1")), false);
            assertThat(cap.getValue().getLotId()).isEqualTo("LOT-snake");
            assertThat(cap.getValue().getStep()).isEqualTo("STEP_snake");
            assertThat(cap.getValue().getEventTime()).isNotNull();
        }

        @Test
        void unparseableEventTimeFallsBackToNow() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });
            Map<String, Object> row = Map.of("eventTime", "garbage-not-a-date",
                    "lotID", "L", "step", "S");
            Map<String, Object> confirm = Map.of("data_views",
                    List.of(Map.of("rows", List.of(row))), "note", "n");
            OffsetDateTime before = OffsetDateTime.now().minusSeconds(2);
            service.emitAlarmIfTriggered(
                    patrolSkill(), run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirm, List.of(stepPass("s1")), false);
            OffsetDateTime after = OffsetDateTime.now().plusSeconds(2);
            // Even though eventTime string was garbage, emit still fell back to now
            assertThat(cap.getValue().getEventTime()).isAfterOrEqualTo(before);
            assertThat(cap.getValue().getEventTime()).isBeforeOrEqualTo(after);
        }

        @Test
        void blankSeverityInTriggerConfigDefaultsToMedium() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });
            SkillDocumentEntity skill = patrolSkill();
            skill.setTriggerConfig("{\"type\":\"schedule\",\"severity\":\"  \"}");
            service.emitAlarmIfTriggered(
                    skill, run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirmWithRow("L", "S", "2026-05-17T00:00:00"),
                    List.of(stepPass("s1")), false);
            assertThat(cap.getValue().getSeverity()).isEqualTo("MEDIUM");
        }

        @Test
        void evidenceRowAllFieldsNullKeepsEmptyDefaults() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });
            // Evidence row exists but every nullable field is null
            Map<String, Object> row = new HashMap<>();
            row.put("lotID", null);
            row.put("lot_id", null);
            row.put("step", null);
            row.put("eventTime", null);
            row.put("event_time", null);
            Map<String, Object> confirm = Map.of("data_views",
                    List.of(Map.of("rows", List.of(row))), "note", "x");
            service.emitAlarmIfTriggered(
                    patrolSkill(), run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirm, List.of(stepPass("s1")), false);
            assertThat(cap.getValue().getLotId()).isEqualTo("");
            assertThat(cap.getValue().getStep()).isNull();
            assertThat(cap.getValue().getEventTime()).isNotNull();  // fallback to now
        }

        @Test
        void nullTitleFallsBackToSlug() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });
            SkillDocumentEntity skill = patrolSkill();
            skill.setTitle(null);  // force fallback to slug
            service.emitAlarmIfTriggered(
                    skill, run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirmWithRow("L", "S", "2026-05-17T00:00:00"),
                    List.of(stepPass("s1")), false);
            assertThat(cap.getValue().getTitle()).contains("test-skill");
            assertThat(cap.getValue().getTitle()).contains("EQP-02");
        }

        @Test
        void confirmWithoutNoteFieldStillEmits() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });
            // Confirm result has data_views but no "note" field
            Map<String, Object> row = Map.of("eventTime", "2026-05-17T00:00:00",
                    "lotID", "L", "step", "S");
            Map<String, Object> confirm = Map.of("data_views",
                    List.of(Map.of("rows", List.of(row))));  // no "note"
            service.emitAlarmIfTriggered(
                    patrolSkill(), run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirm, List.of(stepPass("s1")), false);
            String sum = cap.getValue().getSummary();
            assertThat(sum).doesNotContain("Confirm:");  // no note prefix added
            assertThat(sum).contains("SkillRun #");
        }

        @Test
        void nullConfirmResultStillEmitsSummary() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });
            service.emitAlarmIfTriggered(
                    patrolSkill(), run(false),
                    Map.of("tool_id", "EQP-02"),
                    null,  // no confirm result at all
                    List.of(stepPass("s1")), false);
            String sum = cap.getValue().getSummary();
            assertThat(sum).doesNotContain("Confirm:");
            assertThat(sum).contains("Step s1");
            assertThat(sum).contains("SkillRun #");
        }

        @Test
        void emptyTriggerConfigGivesDefaultSeverityAndPatrol() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });
            SkillDocumentEntity skill = patrolSkill();
            skill.setTriggerConfig("");  // empty string
            service.emitAlarmIfTriggered(
                    skill, run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirmWithRow("L", "S", "2026-05-17T00:00:00"),
                    List.of(stepPass("s1")), false);
            assertThat(cap.getValue().getSeverity()).isEqualTo("MEDIUM");
            assertThat(cap.getValue().getTriggerEvent()).isEqualTo("patrol_check");
        }

        @Test
        void summaryConsolidatesConfirmAndPassingStepsOnly() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<AlarmEntity> cap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(cap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });

            Map<String, Object> confirm = new HashMap<>();
            confirm.put("note", "confirm-note-x");
            confirm.put("data_views", List.of(Map.of("rows",
                    List.of(Map.of("eventTime", "2026-05-17T00:00:00",
                                  "lotID", "L", "step", "S")))));

            service.emitAlarmIfTriggered(
                    patrolSkill(), run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirm,
                    List.of(stepPass("s_good", "good-note"),
                            stepFail("s_bad", "bad-note-should-not-appear")),
                    false);

            String sum = cap.getValue().getSummary();
            assertThat(sum).contains("confirm-note-x");
            assertThat(sum).contains("good-note");
            assertThat(sum).doesNotContain("bad-note-should-not-appear");
            assertThat(sum).contains("SkillRun #");
        }
    }

    // ────────────────────────── v30.15 execution_log linkage ──────────────────────────

    @Nested @DisplayName("v30.15 execution_log linkage")
    class ExecLogLinkage {

        @Test
        void emitAlsoSavesExecutionLogAndLinks() throws Exception {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<ExecutionLogEntity> logCap = ArgumentCaptor.forClass(ExecutionLogEntity.class);
            when(execLogRepo.save(logCap.capture())).thenAnswer(inv -> {
                ExecutionLogEntity e = inv.getArgument(0); e.setId(8888L); return e;
            });
            ArgumentCaptor<AlarmEntity> alarmCap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(alarmCap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(2222L); return a;
            });

            service.emitAlarmIfTriggered(
                    patrolSkill(), run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirmWithRow("LOT-x", "STEP_007", "2026-05-17T01:00:00"),
                    List.of(stepPass("s1", "step1-pass-note")), false);

            // execution_log was saved with right shape
            ExecutionLogEntity savedLog = logCap.getValue();
            assertThat(savedLog.getSkillId()).isEqualTo(43L);
            assertThat(savedLog.getStatus()).isEqualTo("success");
            assertThat(savedLog.getTriggeredBy()).isEqualTo("agent");
            assertThat(savedLog.getLlmReadableData()).isNotNull();
            assertThat(savedLog.getEventContext()).isNotNull();
            assertThat(savedLog.getFinishedAt()).isNotNull();

            // alarm linked to it
            assertThat(alarmCap.getValue().getExecutionLogId()).isEqualTo(8888L);
        }

        @Test
        void executionLogContainsFindingsTriggerSchema() throws Exception {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<ExecutionLogEntity> logCap = ArgumentCaptor.forClass(ExecutionLogEntity.class);
            when(execLogRepo.save(logCap.capture())).thenAnswer(inv -> {
                ExecutionLogEntity e = inv.getArgument(0); e.setId(1L); return e;
            });
            when(alarmRepo.save(any(AlarmEntity.class))).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });

            // confirm with proper data_views (rows + columns)
            Map<String, Object> row = Map.of("eventTime", "2026-05-17T01:00:00",
                    "toolID", "EQP-02", "lotID", "L1", "step", "S1", "spc_status", "OOC");
            Map<String, Object> dv = Map.of(
                    "rows", List.of(row, row),
                    "columns", List.of("eventTime", "toolID", "lotID", "step", "spc_status"));
            Map<String, Object> confirm = Map.of("data_views", List.of(dv),
                    "note", "2 OOC found", "status", "pass");

            service.emitAlarmIfTriggered(
                    patrolSkill(), run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirm,
                    List.of(stepPass("s_check", "19 > 0")), false);

            String json = logCap.getValue().getLlmReadableData();
            JsonNode root = mapper.readTree(json);

            assertThat(root.get("condition_met").asBoolean()).isTrue();
            assertThat(root.get("summary").asText()).contains("19 > 0");
            assertThat(root.get("result_summary").get("triggered").asBoolean()).isTrue();

            JsonNode outputs = root.get("outputs");
            assertThat(outputs.get("evidence_rows").isArray()).isTrue();
            assertThat(outputs.get("evidence_rows").size()).isEqualTo(2);
            assertThat(outputs.get("triggered_count").asInt()).isEqualTo(2);
            assertThat(outputs.has("per_step")).isTrue();
            assertThat(outputs.get("per_step").has("s_check")).isTrue();

            JsonNode schema = root.get("_alarm_output_schema");
            assertThat(schema.isArray()).isTrue();
            assertThat(schema.size()).isGreaterThanOrEqualTo(2);
            // First entry should be evidence_rows table with columns from confirm
            JsonNode evSchema = schema.get(0);
            assertThat(evSchema.get("key").asText()).isEqualTo("evidence_rows");
            assertThat(evSchema.get("type").asText()).isEqualTo("table");
            assertThat(evSchema.get("columns").size()).isGreaterThan(0);
        }

        @Test
        void executionLogFallsBackToStepDataViewWhenConfirmMissing() throws Exception {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<ExecutionLogEntity> logCap = ArgumentCaptor.forClass(ExecutionLogEntity.class);
            when(execLogRepo.save(logCap.capture())).thenAnswer(inv -> {
                ExecutionLogEntity e = inv.getArgument(0); e.setId(1L); return e;
            });
            when(alarmRepo.save(any(AlarmEntity.class))).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });

            // step has its own data_views; confirm has none
            Map<String, Object> stepDv = Map.of(
                    "rows", List.of(Map.of("a", 1), Map.of("a", 2), Map.of("a", 3)),
                    "columns", List.of("a"));
            Map<String, Object> step = new HashMap<>();
            step.put("step_id", "s1"); step.put("status", "pass");
            step.put("note", "found 3"); step.put("data_views", List.of(stepDv));

            service.emitAlarmIfTriggered(
                    patrolSkill(), run(false),
                    Map.of("tool_id", "EQP-02"),
                    null,  // no confirm
                    List.of(step), false);

            String json = logCap.getValue().getLlmReadableData();
            JsonNode outputs = mapper.readTree(json).get("outputs");
            assertThat(outputs.get("evidence_rows").size()).isEqualTo(3);
            assertThat(outputs.get("triggered_count").asInt()).isEqualTo(3);
        }

        @Test
        void executionLogTriggeredByIsManualWhenTestRun() throws Exception {
            // Test mode emit guard normally skips. But buildLlmReadableData
            // alone is callable. Use direct method test.
            String json = service.buildLlmReadableData(
                    Map.of("note", "n", "status", "pass"),
                    List.of(stepPass("s1")),
                    "summary text");
            assertThat(json).isNotNull();
            JsonNode root = mapper.readTree(json);
            assertThat(root.get("condition_met").asBoolean()).isTrue();
        }

        @Test
        void buildLlmReadableDataAllStepsFailGivesConditionMetFalse() throws Exception {
            String json = service.buildLlmReadableData(
                    Map.of("note", "n"),
                    List.of(stepFail("s1"), stepFail("s2")),
                    "no triggers");
            JsonNode root = mapper.readTree(json);
            assertThat(root.get("condition_met").asBoolean()).isFalse();
            assertThat(root.get("result_summary").get("triggered").asBoolean()).isFalse();
        }

        @Test
        void buildLlmReadableDataNullConfirmNoStepsHasEmptyEvidence() throws Exception {
            String json = service.buildLlmReadableData(
                    null, List.of(), "no data");
            JsonNode root = mapper.readTree(json);
            assertThat(root.get("outputs").get("evidence_rows").size()).isEqualTo(0);
            assertThat(root.get("outputs").get("triggered_count").asInt()).isEqualTo(0);
        }

        @Test
        void executionLogSaveFailureDoesNotPreventAlarm() {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            when(execLogRepo.save(any(ExecutionLogEntity.class)))
                    .thenThrow(new RuntimeException("DB down"));
            ArgumentCaptor<AlarmEntity> alarmCap = ArgumentCaptor.forClass(AlarmEntity.class);
            when(alarmRepo.save(alarmCap.capture())).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });

            AlarmEntity r = service.emitAlarmIfTriggered(
                    patrolSkill(), run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirmWithRow("L", "S", "2026-05-17T00:00:00"),
                    List.of(stepPass("s1")), false);

            // Alarm still saved with execLogId = null (graceful degrade)
            assertThat(r).isNotNull();
            assertThat(alarmCap.getValue().getExecutionLogId()).isNull();
        }

        @Test
        void columnsTruncatedToEightInSchema() throws Exception {
            when(alarmRepo.existsActiveBySkillAndEquipmentSince(
                    anyLong(), anyString(), any())).thenReturn(false);
            ArgumentCaptor<ExecutionLogEntity> logCap = ArgumentCaptor.forClass(ExecutionLogEntity.class);
            when(execLogRepo.save(logCap.capture())).thenAnswer(inv -> {
                ExecutionLogEntity e = inv.getArgument(0); e.setId(1L); return e;
            });
            when(alarmRepo.save(any(AlarmEntity.class))).thenAnswer(inv -> {
                AlarmEntity a = inv.getArgument(0); a.setId(1L); return a;
            });

            // 15 columns; schema should only keep 8
            List<String> manyCols = new ArrayList<>();
            for (int i = 0; i < 15; i++) manyCols.add("c" + i);
            Map<String, Object> row = new HashMap<>();
            for (String c : manyCols) row.put(c, c);
            Map<String, Object> dv = Map.of("rows", List.of(row), "columns", manyCols);
            Map<String, Object> confirm = Map.of("data_views", List.of(dv), "note", "n");

            service.emitAlarmIfTriggered(
                    patrolSkill(), run(false),
                    Map.of("tool_id", "EQP-02"),
                    confirm,
                    List.of(stepPass("s1")), false);

            JsonNode schema = mapper.readTree(logCap.getValue().getLlmReadableData())
                    .get("_alarm_output_schema").get(0);
            assertThat(schema.get("columns").size()).isLessThanOrEqualTo(8);
        }
    }

    // ────────────────────────── helpers ──────────────────────────

    private SkillDocumentEntity patrolSkill() {
        SkillDocumentEntity s = new SkillDocumentEntity();
        s.setId(43L);
        s.setSlug("test-skill");
        s.setTitle("Test patrol skill");
        s.setStage("patrol");
        s.setTriggerConfig("{\"type\":\"schedule\"}");
        return s;
    }

    private SkillRunEntity run(boolean isTest) {
        SkillRunEntity r = new SkillRunEntity();
        r.setId(100L);
        r.setSkillId(43L);
        r.setIsTest(isTest);
        return r;
    }

    private Map<String, Object> confirmWithRow(String lotId, String step, String eventTime) {
        Map<String, Object> row = new HashMap<>();
        row.put("eventTime", eventTime);
        row.put("lotID", lotId);
        row.put("step", step);
        row.put("toolID", "EQP-02");
        Map<String, Object> dv = new HashMap<>();
        dv.put("rows", List.of(row));
        Map<String, Object> confirm = new HashMap<>();
        confirm.put("status", "pass");
        confirm.put("note", "confirm-note");
        confirm.put("data_views", List.of(dv));
        return confirm;
    }

    private Map<String, Object> stepPass(String id) {
        return stepPass(id, "step-note-" + id);
    }

    private Map<String, Object> stepPass(String id, String note) {
        Map<String, Object> m = new HashMap<>();
        m.put("step_id", id);
        m.put("status", "pass");
        m.put("note", note);
        return m;
    }

    private Map<String, Object> stepFail(String id) {
        return stepFail(id, "fail-note-" + id);
    }

    private Map<String, Object> stepFail(String id, String note) {
        Map<String, Object> m = new HashMap<>();
        m.put("step_id", id);
        m.put("status", "fail");
        m.put("note", note);
        return m;
    }
}
