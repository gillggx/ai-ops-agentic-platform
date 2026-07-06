package com.aiops.api.api.agentepisode;

import com.aiops.api.common.ApiException;
import com.aiops.api.domain.agentepisode.AgentEpisodeEntity;
import com.aiops.api.domain.agentepisode.AgentEpisodeRepository;
import com.aiops.api.domain.agentepisode.AgentStepEntity;
import com.aiops.api.domain.agentepisode.AgentStepRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/** Pure-Mockito tests (no Spring context) — V69 observability write path. */
class AgentEpisodeServiceTest {

    private AgentEpisodeRepository episodes;
    private AgentStepRepository steps;
    private AgentEpisodeService service;

    @BeforeEach
    void setUp() {
        episodes = mock(AgentEpisodeRepository.class);
        steps = mock(AgentStepRepository.class);
        service = new AgentEpisodeService(episodes, steps, new ObjectMapper());
        when(episodes.save(any())).thenAnswer(inv -> {
            AgentEpisodeEntity e = inv.getArgument(0);
            if (e.getId() == null) e.setId(1L);
            return e;
        });
        when(steps.saveAll(anyList())).thenAnswer(inv -> inv.getArgument(0));
    }

    private AgentEpisodeEntity existing(String key) {
        AgentEpisodeEntity ep = new AgentEpisodeEntity();
        ep.setId(1L);
        ep.setEpisodeKey(key);
        ep.setStartedAt(java.time.OffsetDateTime.now());
        return ep;
    }

    @Test
    void upsert_isIdempotentByKey() {
        when(episodes.findByEpisodeKey("s1")).thenReturn(Optional.empty());
        AgentEpisodeEntity created = service.upsert("s1", 7L, "查 xbar", null, "chat");
        assertThat(created.getEpisodeKey()).isEqualTo("s1");
        assertThat(created.getUserId()).isEqualTo(7L);

        when(episodes.findByEpisodeKey("s1")).thenReturn(Optional.of(created));
        AgentEpisodeEntity again = service.upsert("s1", null, null, null, null);
        assertThat(again.getId()).isEqualTo(created.getId());
        assertThat(again.getInstruction()).isEqualTo("查 xbar"); // not clobbered
    }

    @Test
    void upsert_requiresKey() {
        assertThatThrownBy(() -> service.upsert(" ", null, null, null, null))
                .isInstanceOf(ApiException.class);
    }

    @Test
    void appendSteps_autoCreatesStubForUnknownEpisode_andSkipsMalformed() {
        when(episodes.findByEpisodeKey("lost")).thenReturn(Optional.empty());
        int written = service.appendSteps("lost", List.of(
                Map.of("agent", "builder", "event_type", "param_reject_fix",
                        "phase_id", "p2",
                        "payload", Map.of("block", "block_filter", "param", "value"),
                        "input_tokens", 100, "ts", "2026-07-02T10:00:00Z"),
                Map.of("event_type", "no_agent_field")  // malformed → skipped
        ));
        assertThat(written).isEqualTo(1);

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<AgentStepEntity>> cap = ArgumentCaptor.forClass(List.class);
        org.mockito.Mockito.verify(steps).saveAll(cap.capture());
        AgentStepEntity row = cap.getValue().get(0);
        assertThat(row.getAgent()).isEqualTo("builder");
        assertThat(row.getEventType()).isEqualTo("param_reject_fix");
        assertThat(row.getPayload()).contains("block_filter");
        assertThat(row.getInputTokens()).isEqualTo(100);
    }

    @Test
    void finalize_derivesDivergence_selfOkPlusDeliveryReject() {
        AgentEpisodeEntity ep = existing("s2");
        ep.setUserFeedback("[{\"stage\":\"delivery\",\"sentiment\":\"reject\",\"text\":\"不是我要的\"}]");
        when(episodes.findByEpisodeKey("s2")).thenReturn(Optional.of(ep));

        AgentEpisodeEntity done = service.finalizeEpisode("s2", Map.of(
                "status", "finished",
                "self_assessment", Map.of("ok", true)));
        assertThat(done.isDivergence()).isTrue();
        assertThat(done.getStatus()).isEqualTo("finished");
        assertThat(done.getFinishedAt()).isNotNull();
    }

    @Test
    void finalize_noDivergence_whenSelfFailed() {
        AgentEpisodeEntity ep = existing("s3");
        ep.setUserFeedback("[{\"stage\":\"delivery\",\"sentiment\":\"reject\",\"text\":\"x\"}]");
        when(episodes.findByEpisodeKey("s3")).thenReturn(Optional.of(ep));

        AgentEpisodeEntity done = service.finalizeEpisode("s3", Map.of(
                "self_assessment", Map.of("ok", false)));
        assertThat(done.isDivergence()).isFalse();
    }

    @Test
    void appendFeedback_appendsAndDerives() {
        AgentEpisodeEntity ep = existing("s4");
        ep.setSelfAssessment("{\"ok\":true}");
        when(episodes.findByEpisodeKey("s4")).thenReturn(Optional.of(ep));

        AgentEpisodeEntity after = service.appendFeedback("s4", "delivery", "reject", "圖種錯了");
        assertThat(after.isDivergence()).isTrue();
        assertThat(after.getUserFeedback()).contains("圖種錯了");

        // plan-stage edit does NOT trigger divergence
        AgentEpisodeEntity ep2 = existing("s5");
        ep2.setSelfAssessment("{\"ok\":true}");
        when(episodes.findByEpisodeKey("s5")).thenReturn(Optional.of(ep2));
        AgentEpisodeEntity after2 = service.appendFeedback("s5", "plan", "edit", "改時間窗");
        assertThat(after2.isDivergence()).isFalse();
    }

    @Test
    void appendFeedback_requiresSentiment() {
        when(episodes.findByEpisodeKey("s6")).thenReturn(Optional.of(existing("s6")));
        assertThatThrownBy(() -> service.appendFeedback("s6", "delivery", " ", "x"))
                .isInstanceOf(ApiException.class);
    }
}
