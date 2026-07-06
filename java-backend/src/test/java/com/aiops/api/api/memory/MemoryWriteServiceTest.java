package com.aiops.api.api.memory;

import com.aiops.api.common.ApiException;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeEntity;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeRepository;
import com.aiops.api.domain.agentknowledge.BlockDocMemoEntity;
import com.aiops.api.domain.agentknowledge.BlockDocMemoRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

/** Pure-Mockito tests — V70 memory-layer write path (W1-W3 sinks). */
class MemoryWriteServiceTest {

    private AgentKnowledgeRepository knowledge;
    private BlockDocMemoRepository memos;
    private MemoryWriteService service;

    @BeforeEach
    void setUp() {
        knowledge = mock(AgentKnowledgeRepository.class);
        memos = mock(BlockDocMemoRepository.class);
        service = new MemoryWriteService(knowledge, memos);
        when(knowledge.save(any())).thenAnswer(inv -> {
            AgentKnowledgeEntity e = inv.getArgument(0);
            e.setId(9L);
            return e;
        });
        when(memos.save(any())).thenAnswer(inv -> {
            BlockDocMemoEntity m = inv.getArgument(0);
            m.setId(5L);
            return m;
        });
    }

    @Test
    void createKnowledge_setsClassScopeActiveAndSource() {
        when(knowledge.findFirstByUserIdAndMemoClassAndTitle(any(), any(), any()))
                .thenReturn(Optional.empty());
        Map<String, Object> out = service.createKnowledge(
                1L, "preference", "偏好:預設時間窗 12 小時",
                "user 在 plan 將 24h 改為 12h(2026-07-03)。**Why:** user 明改。"
                        + "**How to apply:** 同類需求預設 12h。", "plan", null, null, "planner");
        assertThat(out).containsEntry("deduped", false).containsEntry("id", 9L);

        ArgumentCaptor<AgentKnowledgeEntity> cap = ArgumentCaptor.forClass(AgentKnowledgeEntity.class);
        verify(knowledge).save(cap.capture());
        AgentKnowledgeEntity e = cap.getValue();
        assertThat(e.getMemoClass()).isEqualTo("preference");
        assertThat(e.getScopeType()).isEqualTo("global");   // per-user = user_id filter
        assertThat(e.getUserId()).isEqualTo(1L);
        assertThat(e.getActive()).isTrue();                 // E2: effective immediately
        assertThat(e.getSource()).isEqualTo("agent_fast");
        assertThat(e.getAppliesTo()).isEqualTo("plan");
        assertThat(e.getWrittenBy()).isEqualTo("planner");  // V71 provenance
    }

    @Test
    void createKnowledge_writtenBy_invalidBecomesNull_validKept() {
        when(knowledge.findFirstByUserIdAndMemoClassAndTitle(any(), any(), any()))
                .thenReturn(Optional.empty());
        ArgumentCaptor<AgentKnowledgeEntity> cap = ArgumentCaptor.forClass(AgentKnowledgeEntity.class);

        service.createKnowledge(1L, "correction", "t1", "b", null, null, false, "repair");
        service.createKnowledge(1L, "correction", "t2", "b", null, null, false, "bogus");
        verify(knowledge, org.mockito.Mockito.times(2)).save(cap.capture());
        assertThat(cap.getAllValues().get(0).getWrittenBy()).isEqualTo("repair");
        assertThat(cap.getAllValues().get(1).getWrittenBy()).isNull();  // invalid → honest null
    }

    @Test
    void createKnowledge_dedupsByUserClassTitle() {
        AgentKnowledgeEntity existing = new AgentKnowledgeEntity();
        existing.setId(3L);
        when(knowledge.findFirstByUserIdAndMemoClassAndTitle(1L, "preference", "T"))
                .thenReturn(Optional.of(existing));
        Map<String, Object> out = service.createKnowledge(1L, "preference", "T", "b", null, null, null, null);
        assertThat(out).containsEntry("deduped", true).containsEntry("id", 3L);
        verify(knowledge, never()).save(any());
    }

    @Test
    void createKnowledge_rejectsBadClassAndMissingFields() {
        assertThatThrownBy(() -> service.createKnowledge(1L, "vibes", "t", "b", null, null, null, null))
                .isInstanceOf(ApiException.class);
        assertThatThrownBy(() -> service.createKnowledge(1L, "domain", " ", "b", null, null, null, null))
                .isInstanceOf(ApiException.class);
        assertThatThrownBy(() -> service.createKnowledge(null, "domain", "t", "b", null, null, null, null))
                .isInstanceOf(ApiException.class);
    }

    @Test
    void createKnowledge_defaultsAppliesToBothOnBadValue() {
        when(knowledge.findFirstByUserIdAndMemoClassAndTitle(any(), any(), any()))
                .thenReturn(Optional.empty());
        service.createKnowledge(1L, "correction", "t", "b", "weird", null, null, null);
        ArgumentCaptor<AgentKnowledgeEntity> cap = ArgumentCaptor.forClass(AgentKnowledgeEntity.class);
        verify(knowledge).save(cap.capture());
        assertThat(cap.getValue().getAppliesTo()).isEqualTo("both");
    }

    @Test
    void createKnowledge_correctionDraftWhenActiveFalse() {
        when(knowledge.findFirstByUserIdAndMemoClassAndTitle(any(), any(), any()))
                .thenReturn(Optional.empty());
        service.createKnowledge(1L, "correction", "t", "b", "execute", null, false, null);
        ArgumentCaptor<AgentKnowledgeEntity> cap = ArgumentCaptor.forClass(AgentKnowledgeEntity.class);
        verify(knowledge).save(cap.capture());
        assertThat(cap.getValue().getActive()).isFalse();   // draft until Supervisor promotes
    }

    // ── V75 lifecycle status derivation ─────────────────────────────────

    @Test
    void createKnowledge_v75StatusDerivation() {
        when(knowledge.findFirstByUserIdAndMemoClassAndTitle(any(), any(), any()))
                .thenReturn(Optional.empty());
        ArgumentCaptor<AgentKnowledgeEntity> cap = ArgumentCaptor.forClass(AgentKnowledgeEntity.class);

        // W3 convention: repair-written inactive correction → draft
        service.createKnowledge(1L, "correction", "t1", "b", null, null, false, "repair",
                null, null, null);
        // other inactive rows → archived
        service.createKnowledge(1L, "preference", "t2", "b", null, null, false, "planner",
                null, null, null);
        // explicit whitelisted status wins
        service.createKnowledge(1L, "domain", "t3", "b", null, null, null, "planner",
                "draft", null, null);
        // non-whitelisted status ignored → live default 'active'
        service.createKnowledge(1L, "domain", "t4", "b", null, null, null, "planner",
                "stale", "block", "block_bar_chart");

        verify(knowledge, times(4)).save(cap.capture());
        assertThat(cap.getAllValues().get(0).getStatus()).isEqualTo("draft");
        assertThat(cap.getAllValues().get(1).getStatus()).isEqualTo("archived");
        assertThat(cap.getAllValues().get(2).getStatus()).isEqualTo("draft");
        assertThat(cap.getAllValues().get(3).getStatus()).isEqualTo("active");
        assertThat(cap.getAllValues().get(3).getSubjectKind()).isEqualTo("block");
        assertThat(cap.getAllValues().get(3).getSubjectId()).isEqualTo("block_bar_chart");
    }

    @Test
    void createDocMemo_writesPendingWithProvenance() {
        when(memos.existsByBlockIdAndParamAndFromEpisode(anyString(), any(), any()))
                .thenReturn(false);
        Map<String, Object> out = service.createDocMemo(
                "block_filter", "value", "param value 需為 list 當 operator=in",
                "[{\"reason\":\"...\"}]", "ep-1");
        assertThat(out).containsEntry("deduped", false);
        ArgumentCaptor<BlockDocMemoEntity> cap = ArgumentCaptor.forClass(BlockDocMemoEntity.class);
        verify(memos).save(cap.capture());
        assertThat(cap.getValue().getStatus()).isEqualTo("pending");
        assertThat(cap.getValue().getFromEpisode()).isEqualTo("ep-1");
    }

    @Test
    void createDocMemo_dedupsPerBlockParamEpisode() {
        when(memos.existsByBlockIdAndParamAndFromEpisode("block_filter", "value", "ep-1"))
                .thenReturn(true);
        Map<String, Object> out = service.createDocMemo(
                "block_filter", "value", "m", null, "ep-1");
        assertThat(out).containsEntry("deduped", true);
        verify(memos, never()).save(any());
    }
}
