package com.aiops.api.api.agentepisode;

import com.aiops.api.common.ApiException;
import com.aiops.api.domain.agentepisode.AgentEpisodeEntity;
import com.aiops.api.domain.agentepisode.AgentEpisodeRepository;
import com.aiops.api.domain.agentepisode.AgentStepEntity;
import com.aiops.api.domain.agentepisode.AgentStepRepository;
import com.aiops.api.domain.user.UserEntity;
import com.aiops.api.domain.user.UserRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Pure-Mockito tests for the Agent Activity read path (spec
 * MULTI_AGENT_ACTIVITY_UI_SPEC §3). Focus: rounds() merges the BuildTracer JSON
 * per-round prompt/output with the memories each (phase,round) recalled, and
 * degrades gracefully when the trace file is absent.
 */
class AgentActivityServiceTest {

    private AgentEpisodeRepository episodes;
    private AgentStepRepository steps;
    private UserRepository users;
    private AgentActivityService service;

    @BeforeEach
    void setUp() {
        episodes = mock(AgentEpisodeRepository.class);
        steps = mock(AgentStepRepository.class);
        users = mock(UserRepository.class);
        service = new AgentActivityService(episodes, steps, users, new ObjectMapper());
    }

    private AgentEpisodeEntity episode(String key, String traceFile) {
        AgentEpisodeEntity e = new AgentEpisodeEntity();
        e.setId(1L);
        e.setEpisodeKey(key);
        e.setInstruction("查 EQP-01 xbar");
        e.setStatus("success");
        e.setStartedAt(OffsetDateTime.now());
        e.setTraceFile(traceFile);
        return e;
    }

    private AgentStepEntity recallStep(String phaseId, int round, String recalledJson) {
        AgentStepEntity s = new AgentStepEntity();
        s.setAgent("builder");
        s.setPhaseId(phaseId);
        s.setEventType("memory_recall");
        s.setPayload("{\"round\":" + round + ",\"recalled\":" + recalledJson + "}");
        s.setTs(OffsetDateTime.now());
        return s;
    }

    @Test
    void rounds_mergesRecalledMemoriesByPhaseAndRound(@TempDir Path dir) throws Exception {
        Path trace = dir.resolve("t.json");
        Files.writeString(trace, "{\"llm_calls\":["
                + "{\"node\":\"agentic_phase_loop\",\"phase_id\":\"p1\",\"round\":0,"
                + "\"user_msg\":\"build p1\",\"raw_response\":\"ok\",\"input_tokens\":100,"
                + "\"output_tokens\":20,\"cache_read_input_tokens\":80,\"finish_reason\":\"stop\"}]}");

        when(episodes.findByEpisodeKey("ep1")).thenReturn(Optional.of(episode("ep1", trace.toString())));
        when(steps.findByEpisodeIdOrderByTsAsc(anyLong())).thenReturn(List.of(
                recallStep("p1", 0, "[{\"id\":42,\"memo_class\":\"domain\",\"title\":\"SPC=站級\",\"layer\":\"always_on\"}]")));

        Map<String, Object> out = service.rounds("ep1");

        assertThat(out.get("available")).isEqualTo(true);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> rounds = (List<Map<String, Object>>) out.get("rounds");
        assertThat(rounds).hasSize(1);
        Map<String, Object> r0 = rounds.get(0);
        assertThat(r0.get("user_msg")).isEqualTo("build p1");
        assertThat(r0.get("raw_response")).isEqualTo("ok");
        assertThat(r0.get("cache_read")).isEqualTo(80);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> recalled = (List<Map<String, Object>>) r0.get("recalled");
        assertThat(recalled).hasSize(1);
        assertThat(recalled.get(0).get("id")).isEqualTo(42);
        assertThat(recalled.get(0).get("title")).isEqualTo("SPC=站級");
    }

    @Test
    void rounds_plannerGoalPlan_nullTracePhaseRound_matchesStepPhaseBlankRoundZero(@TempDir Path dir)
            throws Exception {
        // The real-world mismatch: goal_plan trace call has phase_id=null/round=null,
        // but the planner memory_recall step emits phase=""/round=0. mergeKey folds both.
        Path trace = dir.resolve("t.json");
        Files.writeString(trace, "{\"llm_calls\":["
                + "{\"node\":\"goal_plan_node\",\"phase_id\":null,\"round\":null,"
                + "\"user_msg\":\"plan it\",\"raw_response\":\"[p1,p2]\"}]}");
        when(episodes.findByEpisodeKey("epP")).thenReturn(Optional.of(episode("epP", trace.toString())));
        AgentStepEntity s = new AgentStepEntity();
        s.setAgent("planner");
        s.setPhaseId("");                 // blank, not null — as stored for goal_plan
        s.setEventType("memory_recall");
        s.setPayload("{\"layer\":\"goal_plan\",\"round\":0,"
                + "\"recalled\":[{\"id\":9,\"title\":\"SPC OOC 慣例\",\"layer\":\"always_on\"}]}");
        s.setTs(OffsetDateTime.now());
        when(steps.findByEpisodeIdOrderByTsAsc(anyLong())).thenReturn(List.of(s));

        Map<String, Object> out = service.rounds("epP");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> rounds = (List<Map<String, Object>>) out.get("rounds");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> recalled = (List<Map<String, Object>>) rounds.get(0).get("recalled");
        assertThat(recalled).hasSize(1);
        assertThat(recalled.get(0).get("id")).isEqualTo(9);
    }

    @Test
    void rounds_missingRecallLeavesEmptyList(@TempDir Path dir) throws Exception {
        Path trace = dir.resolve("t.json");
        Files.writeString(trace, "{\"llm_calls\":["
                + "{\"node\":\"agentic_phase_loop\",\"phase_id\":\"p2\",\"round\":1,"
                + "\"user_msg\":\"m\",\"raw_response\":\"o\"}]}");
        when(episodes.findByEpisodeKey("ep2")).thenReturn(Optional.of(episode("ep2", trace.toString())));
        when(steps.findByEpisodeIdOrderByTsAsc(anyLong())).thenReturn(List.of()); // no recall steps

        Map<String, Object> out = service.rounds("ep2");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> rounds = (List<Map<String, Object>>) out.get("rounds");
        @SuppressWarnings("unchecked")
        List<Object> recalled = (List<Object>) rounds.get(0).get("recalled");
        assertThat(recalled).isEmpty();
    }

    @Test
    void rounds_missingTraceFileReturnsUnavailableNotThrow() {
        when(episodes.findByEpisodeKey("ep3"))
                .thenReturn(Optional.of(episode("ep3", "/no/such/trace.json")));
        when(steps.findByEpisodeIdOrderByTsAsc(anyLong())).thenReturn(List.of(
                recallStep("p1", 0, "[{\"id\":7}]")));

        Map<String, Object> out = service.rounds("ep3");
        assertThat(out.get("available")).isEqualTo(false);
        assertThat(out.get("reason")).asString().contains("/no/such/trace.json");
        // recall_index still returned so the steps view can use it
        assertThat(out.get("recall_index")).isInstanceOf(Map.class);
    }

    @Test
    void rounds_nullTraceFileIsUnavailable() {
        when(episodes.findByEpisodeKey("ep4"))
                .thenReturn(Optional.of(episode("ep4", null)));
        when(steps.findByEpisodeIdOrderByTsAsc(anyLong())).thenReturn(List.of());
        assertThat(service.rounds("ep4").get("available")).isEqualTo(false);
    }

    @Test
    void detail_unknownKeyThrowsNotFound() {
        when(episodes.findByEpisodeKey("nope")).thenReturn(Optional.empty());
        assertThatThrownBy(() -> service.detail("nope")).isInstanceOf(ApiException.class);
    }

    @Test
    void detail_includesCaseMetadata_withDurationAndPhaseCount() {
        OffsetDateTime start = OffsetDateTime.parse("2026-07-01T10:00:00Z");
        OffsetDateTime finish = start.plusSeconds(5); // 5000 ms
        AgentEpisodeEntity e = episode("epM", null);
        e.setUserId(7L);
        e.setStartedAt(start);
        e.setFinishedAt(finish);
        e.setPlanJson("[{\"id\":\"p1\"},{\"id\":\"p2\"},{\"id\":\"p3\"}]");

        UserEntity u = new UserEntity();
        u.setUsername("pe_test");
        when(users.findById(7L)).thenReturn(Optional.of(u));
        when(episodes.findByEpisodeKey("epM")).thenReturn(Optional.of(e));
        when(steps.findByEpisodeIdOrderByTsAsc(anyLong())).thenReturn(List.of());

        Map<String, Object> out = service.detail("epM");

        assertThat(out.get("user_id")).isEqualTo(7L);
        assertThat(out.get("username")).isEqualTo("pe_test");
        assertThat(out.get("started_at")).isEqualTo(start.toString());
        assertThat(out.get("finished_at")).isEqualTo(finish.toString());
        assertThat(out.get("duration_ms")).isEqualTo(5000L);
        assertThat(out.get("phase_count")).isEqualTo(3);
        // existing keys untouched
        assertThat(out.get("episode_key")).isEqualTo("epM");
        assertThat(out.get("status")).isEqualTo("success");
    }

    @Test
    void detail_durationNull_whenFinishedAtNull() {
        AgentEpisodeEntity e = episode("epN", null);
        e.setUserId(null);                 // also exercise null user -> null username
        e.setStartedAt(OffsetDateTime.parse("2026-07-01T10:00:00Z"));
        e.setFinishedAt(null);
        e.setPlanJson(null);               // null plan -> phase_count 0

        when(episodes.findByEpisodeKey("epN")).thenReturn(Optional.of(e));
        when(steps.findByEpisodeIdOrderByTsAsc(anyLong())).thenReturn(List.of());

        Map<String, Object> out = service.detail("epN");

        assertThat(out.get("finished_at")).isNull();
        assertThat(out.get("duration_ms")).isNull();
        assertThat(out.get("user_id")).isNull();
        assertThat(out.get("username")).isNull();
        assertThat(out.get("phase_count")).isEqualTo(0);
    }

    @Test
    void list_rowIncludesUserIdAndFinishedAt() {
        OffsetDateTime finish = OffsetDateTime.parse("2026-07-01T11:00:00Z");
        AgentEpisodeEntity e = episode("epL", null);
        e.setUserId(9L);
        e.setFinishedAt(finish);
        when(episodes.findAllByOrderByIdDesc(org.mockito.ArgumentMatchers.any()))
                .thenReturn(List.of(e));
        when(steps.countByEpisodeId(anyLong())).thenReturn(4L);

        List<Map<String, Object>> rows = service.list(10);

        assertThat(rows).hasSize(1);
        assertThat(rows.get(0).get("user_id")).isEqualTo(9L);
        assertThat(rows.get(0).get("finished_at")).isEqualTo(finish.toString());
    }
}
