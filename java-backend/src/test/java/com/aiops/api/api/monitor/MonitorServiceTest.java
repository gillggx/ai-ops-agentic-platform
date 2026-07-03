package com.aiops.api.api.monitor;

import com.aiops.api.common.ApiException;
import com.aiops.api.domain.agentepisode.AgentEpisodeRepository;
import com.aiops.api.domain.agentepisode.AgentStepRepository;
import com.aiops.api.domain.agentknowledge.BlockDocMemoRepository;
import com.aiops.api.domain.monitor.MonitorRequestEntity;
import com.aiops.api.domain.monitor.MonitorRequestRepository;
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
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

/** Pure-Mockito tests — Phase 6 monitor scan thresholds + review flow. */
class MonitorServiceTest {

    private MonitorRequestRepository requests;
    private BlockDocMemoRepository docMemos;
    private AgentEpisodeRepository episodes;
    private AgentStepRepository steps;
    private MonitorService service;

    @BeforeEach
    void setUp() {
        requests = mock(MonitorRequestRepository.class);
        docMemos = mock(BlockDocMemoRepository.class);
        episodes = mock(AgentEpisodeRepository.class);
        steps = mock(AgentStepRepository.class);
        service = new MonitorService(requests, docMemos, episodes, steps, new ObjectMapper());
        when(requests.save(any())).thenAnswer(inv -> {
            MonitorRequestEntity r = inv.getArgument(0);
            if (r.getId() == null) r.setId(1L);
            return r;
        });
        when(requests.existsByKindAndSubjectAndStatus(anyString(), anyString(), anyString()))
                .thenReturn(false);
        // defaults: everything below threshold
        when(docMemos.pendingCountsByBlock(anyLong())).thenReturn(List.of());
        when(episodes.countByDivergenceTrueAndStartedAtAfter(any())).thenReturn(0L);
        when(episodes.countByStartedAtAfter(any())).thenReturn(10L);
        when(steps.countRepairHandoversAfter(any())).thenReturn(0L);
        when(steps.countByEventTypeAndTsAfter(anyString(), any())).thenReturn(0L);
    }

    @Test
    void scan_quietSystemFilesNothing() {
        Map<String, Object> out = service.scan();
        assertThat(out.get("created")).isEqualTo(0);
        verify(requests, never()).save(any());
    }

    @Test
    void scan_docGapOverThresholdFilesRequestWithEvidence() {
        when(docMemos.pendingCountsByBlock(anyLong()))
                .thenReturn(List.<Object[]>of(new Object[]{"block_union", 5L}));

        Map<String, Object> out = service.scan();

        assertThat(out.get("created")).isEqualTo(1);
        ArgumentCaptor<MonitorRequestEntity> cap = ArgumentCaptor.forClass(MonitorRequestEntity.class);
        verify(requests).save(cap.capture());
        MonitorRequestEntity r = cap.getValue();
        assertThat(r.getKind()).isEqualTo("DOC_GAP");
        assertThat(r.getSubject()).isEqualTo("block_union");
        assertThat(r.getEvidence()).contains("pending_doc_memos");
        assertThat(r.getSuggestedInstruction()).contains("block_union");
        assertThat(r.getStatus()).isEqualTo("open");
    }

    @Test
    void scan_divergenceAndHandoverThresholds() {
        when(episodes.countByDivergenceTrueAndStartedAtAfter(any()))
                .thenReturn(MonitorService.DIVERGENCE_MIN);
        when(steps.countRepairHandoversAfter(any()))
                .thenReturn(MonitorService.HANDOVER_MIN);
        when(steps.countByEventTypeAndTsAfter(eq("repair_outcome"), any())).thenReturn(9L);

        Map<String, Object> out = service.scan();

        assertThat(out.get("created")).isEqualTo(2);
        ArgumentCaptor<MonitorRequestEntity> cap = ArgumentCaptor.forClass(MonitorRequestEntity.class);
        verify(requests, times(2)).save(cap.capture());
        assertThat(cap.getAllValues())
                .extracting(MonitorRequestEntity::getKind)
                .containsExactlyInAnyOrder("DIVERGENCE", "REPAIR_HANDOVER");
    }

    @Test
    void scan_dedupsOpenRequests() {
        when(docMemos.pendingCountsByBlock(anyLong()))
                .thenReturn(List.<Object[]>of(new Object[]{"block_union", 5L}));
        when(requests.existsByKindAndSubjectAndStatus("DOC_GAP", "block_union", "open"))
                .thenReturn(true);

        Map<String, Object> out = service.scan();

        assertThat(out.get("created")).isEqualTo(0);
        assertThat(out.get("deduped")).isEqualTo(1);
        verify(requests, never()).save(any());
    }

    @Test
    void review_approveReturnsInstruction_dismissJustStamps() {
        MonitorRequestEntity r = new MonitorRequestEntity();
        r.setId(9L);
        r.setStatus("open");
        r.setSuggestedInstruction("檢視 block_union 文件");
        when(requests.findById(9L)).thenReturn(Optional.of(r));

        Map<String, Object> ok = service.review(9L, 42L, true);
        assertThat(ok.get("status")).isEqualTo("approved");
        assertThat(String.valueOf(ok.get("suggested_instruction"))).contains("block_union");
        assertThat(r.getReviewedBy()).isEqualTo(42L);

        // second review of same request must fail (already approved)
        assertThatThrownBy(() -> service.review(9L, 42L, false))
                .isInstanceOf(ApiException.class);
    }
}
