package com.aiops.api.api.supervisor;

import com.aiops.api.common.ApiException;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeEntity;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeRepository;
import com.aiops.api.domain.agentknowledge.BlockDocMemoEntity;
import com.aiops.api.domain.agentknowledge.BlockDocMemoRepository;
import com.aiops.api.domain.supervisor.SupervisorActionEntity;
import com.aiops.api.domain.supervisor.SupervisorActionRepository;
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
import static org.mockito.Mockito.*;

/**
 * Pure-Mockito tests — Phase 5 Supervisor curation. Focus: propose-only
 * discipline (nothing mutates until approve), per-type commit correctness,
 * and audit stamping.
 */
class SupervisorCurationServiceTest {

    private SupervisorActionRepository actions;
    private AgentKnowledgeRepository knowledge;
    private BlockDocMemoRepository docMemos;
    private SupervisorCurationService service;

    @BeforeEach
    void setUp() {
        actions = mock(SupervisorActionRepository.class);
        knowledge = mock(AgentKnowledgeRepository.class);
        docMemos = mock(BlockDocMemoRepository.class);
        service = new SupervisorCurationService(actions, knowledge, docMemos, new ObjectMapper());
        when(actions.save(any())).thenAnswer(inv -> {
            SupervisorActionEntity a = inv.getArgument(0);
            if (a.getId() == null) a.setId(77L);
            return a;
        });
        when(knowledge.save(any())).thenAnswer(inv -> {
            AgentKnowledgeEntity e = inv.getArgument(0);
            if (e.getId() == null) e.setId(500L);
            return e;
        });
        when(docMemos.save(any())).thenAnswer(inv -> inv.getArgument(0));
    }

    private SupervisorActionEntity action(long id, String type, String proposalJson) {
        SupervisorActionEntity a = new SupervisorActionEntity();
        a.setId(id);
        a.setActionType(type);
        a.setProposal(proposalJson);
        a.setStatus("proposed");
        return a;
    }

    private AgentKnowledgeEntity krow(long id, boolean active) {
        AgentKnowledgeEntity e = new AgentKnowledgeEntity();
        e.setId(id);
        e.setActive(active);
        e.setTitle("t" + id);
        e.setBody("b" + id);
        return e;
    }

    // ── propose ─────────────────────────────────────────────────────────

    @Test
    void propose_queuesWithoutTouchingKnowledge() {
        when(actions.existsByActionTypeAndTargetIdsAndStatus(any(), any(), any())).thenReturn(false);
        Map<String, Object> out = service.propose("PRUNE", List.of(1, 2),
                Map.of("target_ids", List.of(1, 2)), "stale", Map.of("model", "haiku"), null, null);
        assertThat(out).containsEntry("deduped", false);
        verify(knowledge, never()).save(any());   // propose-only: no mutation
        verify(docMemos, never()).save(any());
    }

    @Test
    void propose_dedupsLiveProposals() {
        when(actions.existsByActionTypeAndTargetIdsAndStatus(any(), any(), any())).thenReturn(true);
        Map<String, Object> out = service.propose("PRUNE", List.of(1),
                Map.of("target_ids", List.of(1)), null, null, null, null);
        assertThat(out).containsEntry("deduped", true);
        verify(actions, never()).save(any());
    }

    @Test
    void propose_rejectsUnknownType() {
        assertThatThrownBy(() -> service.propose("NUKE", List.of(), Map.of("x", 1), null, null, null, null))
                .isInstanceOf(ApiException.class);
    }

    @Test
    void propose_persistsNarrativeAsJson() {
        when(actions.existsByActionTypeAndTargetIdsAndStatus(any(), any(), any())).thenReturn(false);
        service.propose("PRUNE", List.of(1), Map.of("target_ids", List.of(1)), null, null,
                Map.of("happened", "spc-ooc build 反覆失敗", "action", "prune 30 preference"), null);
        ArgumentCaptor<SupervisorActionEntity> cap = ArgumentCaptor.forClass(SupervisorActionEntity.class);
        verify(actions).save(cap.capture());
        assertThat(cap.getValue().getNarrative()).contains("happened");
    }

    // ── approve: per-type commits ───────────────────────────────────────

    @Test
    void approve_merge_keepsWinnerDeactivatesLosers() {
        when(actions.findById(1L)).thenReturn(Optional.of(action(1L, "MERGE",
                "{\"keep_id\":10,\"remove_ids\":[11,12],\"merged_body\":\"merged text\"}")));
        when(knowledge.findById(10L)).thenReturn(Optional.of(krow(10, true)));
        when(knowledge.findById(11L)).thenReturn(Optional.of(krow(11, true)));
        when(knowledge.findById(12L)).thenReturn(Optional.of(krow(12, true)));

        Map<String, Object> dto = service.approve(1L, 99L);

        assertThat(dto.get("status")).isEqualTo("approved");
        ArgumentCaptor<AgentKnowledgeEntity> cap = ArgumentCaptor.forClass(AgentKnowledgeEntity.class);
        verify(knowledge, times(3)).save(cap.capture());
        assertThat(cap.getAllValues().get(0).getBody()).isEqualTo("merged text"); // keeper updated
        assertThat(cap.getAllValues().get(1).getActive()).isFalse();               // losers off
        assertThat(cap.getAllValues().get(2).getActive()).isFalse();
    }

    @Test
    void approve_correct_rewritesAndPromotes() {
        when(actions.findById(2L)).thenReturn(Optional.of(action(2L, "CORRECT",
                "{\"target_id\":20,\"new_title\":\"clean title\",\"new_body\":\"clean body\",\"promote\":true}")));
        AgentKnowledgeEntity draft = krow(20, false);
        when(knowledge.findById(20L)).thenReturn(Optional.of(draft));

        service.approve(2L, 99L);

        assertThat(draft.getTitle()).isEqualTo("clean title");
        assertThat(draft.getBody()).isEqualTo("clean body");
        assertThat(draft.getActive()).isTrue();   // promoted on approve
    }

    @Test
    void approve_prune_deactivates() {
        when(actions.findById(3L)).thenReturn(Optional.of(action(3L, "PRUNE",
                "{\"target_ids\":[30,31]}")));
        when(knowledge.findById(30L)).thenReturn(Optional.of(krow(30, true)));
        when(knowledge.findById(31L)).thenReturn(Optional.of(krow(31, false))); // already off → skip

        Map<String, Object> dto = service.approve(3L, 99L);

        @SuppressWarnings("unchecked")
        Map<String, Object> result = (Map<String, Object>) dto.get("commit_result");
        assertThat(result.get("pruned")).isEqualTo(1);
    }

    @Test
    void approve_promote_createsSupervisorDomainRow() {
        when(actions.findById(4L)).thenReturn(Optional.of(action(4L, "PROMOTE",
                "{\"memo_class\":\"domain\",\"title\":\"SPC 站級規則\",\"body\":\"跨 build 蒸餾出的領域事實\",\"applies_to\":\"plan\"}")));

        service.approve(4L, 99L);

        ArgumentCaptor<AgentKnowledgeEntity> cap = ArgumentCaptor.forClass(AgentKnowledgeEntity.class);
        verify(knowledge).save(cap.capture());
        AgentKnowledgeEntity e = cap.getValue();
        assertThat(e.getMemoClass()).isEqualTo("domain");
        assertThat(e.getWrittenBy()).isEqualTo("supervisor");
        assertThat(e.getSource()).isEqualTo("supervisor");
        assertThat(e.getActive()).isTrue();       // human approved → live
        assertThat(e.getAppliesTo()).isEqualTo("plan");
    }

    @Test
    void approve_promote_rejectsNonDistillClasses() {
        when(actions.findById(5L)).thenReturn(Optional.of(action(5L, "PROMOTE",
                "{\"memo_class\":\"preference\",\"title\":\"t\",\"body\":\"b\"}")));
        assertThatThrownBy(() -> service.approve(5L, 99L)).isInstanceOf(ApiException.class);
        verify(knowledge, never()).save(any());
    }

    @Test
    void approve_docRevise_promotesMemosWithoutTouchingBlockDocs() {
        when(actions.findById(6L)).thenReturn(Optional.of(action(6L, "DOC_REVISE",
                "{\"block_id\":\"block_union\",\"memo_ids\":[40],\"revised_doc_draft\":\"...draft...\"}")));
        BlockDocMemoEntity m = new BlockDocMemoEntity();
        m.setId(40L);
        m.setStatus("pending");
        when(docMemos.findById(40L)).thenReturn(Optional.of(m));

        service.approve(6L, 99L);

        assertThat(m.getStatus()).isEqualTo("promoted");
        assertThat(m.getReviewedBy()).isEqualTo(99L);
        verify(knowledge, never()).save(any());   // block_docs / knowledge untouched
    }

    // ── reject + state guards ───────────────────────────────────────────

    @Test
    void reject_stampsAuditWithoutMutation() {
        when(actions.findById(7L)).thenReturn(Optional.of(action(7L, "PRUNE",
                "{\"target_ids\":[50]}")));
        Map<String, Object> dto = service.reject(7L, 99L, null);
        assertThat(dto.get("status")).isEqualTo("rejected");
        assertThat(dto.get("reviewed_by")).isEqualTo(99L);
        assertThat(dto.get("reject_reason")).isNull();   // optional body omitted
        verify(knowledge, never()).save(any());   // reject = DB untouched
        verify(knowledge, never()).findById(any());
    }

    @Test
    void reject_storesReason() {
        SupervisorActionEntity a = action(9L, "PRUNE", "{\"target_ids\":[50]}");
        when(actions.findById(9L)).thenReturn(Optional.of(a));
        Map<String, Object> dto = service.reject(9L, 99L, "站點慣例不同,此 preference 仍有效");
        assertThat(dto.get("status")).isEqualTo("rejected");
        assertThat(dto.get("reject_reason")).isEqualTo("站點慣例不同,此 preference 仍有效");
        assertThat(a.getRejectReason()).isEqualTo("站點慣例不同,此 preference 仍有效");
    }

    @Test
    void approve_stampsLandedLifecycle() {
        when(actions.findById(10L)).thenReturn(Optional.of(action(10L, "PRUNE",
                "{\"target_ids\":[30]}")));
        when(knowledge.findById(30L)).thenReturn(Optional.of(krow(30, true)));

        Map<String, Object> dto = service.approve(10L, 99L);

        assertThat(dto.get("landed_by")).isEqualTo("99");   // VARCHAR(80) on the wire
        assertThat(dto.get("landed_at")).isNotNull();       // stamped after successful commit
    }

    @Test
    void approve_twiceRejected() {
        SupervisorActionEntity done = action(8L, "PRUNE", "{\"target_ids\":[1]}");
        done.setStatus("approved");
        when(actions.findById(8L)).thenReturn(Optional.of(done));
        assertThatThrownBy(() -> service.approve(8L, 99L)).isInstanceOf(ApiException.class);
        assertThatThrownBy(() -> service.reject(8L, 99L, null)).isInstanceOf(ApiException.class);
    }

    // ── W2 regression fix: proposal / narrative as JSON strings ─────────

    @Test
    void propose_acceptsProposalAndNarrativeAsJsonStrings() {
        // sidecar proposer sends json.dumps strings, not objects
        when(actions.existsByActionTypeAndTargetIdsAndStatus(any(), any(), any())).thenReturn(false);

        Map<String, Object> out = service.propose("PRUNE", List.of(1),
                "{\"target_ids\": [1], \"reason\": \"stale\"}", null, null,
                "{\"happened\": \"spc-ooc 反覆失敗\", \"action\": \"prune\"}", null);

        assertThat(out).containsEntry("deduped", false);
        ArgumentCaptor<SupervisorActionEntity> cap = ArgumentCaptor.forClass(SupervisorActionEntity.class);
        verify(actions).save(cap.capture());
        // stored as-is (exact string), not re-serialized
        assertThat(cap.getValue().getProposal())
                .isEqualTo("{\"target_ids\": [1], \"reason\": \"stale\"}");
        assertThat(cap.getValue().getNarrative())
                .isEqualTo("{\"happened\": \"spc-ooc 反覆失敗\", \"action\": \"prune\"}");
    }

    @Test
    void propose_mapShapesStillWork() {
        when(actions.existsByActionTypeAndTargetIdsAndStatus(any(), any(), any())).thenReturn(false);
        service.propose("PRUNE", List.of(1), Map.of("target_ids", List.of(1)),
                null, null, Map.of("happened", "x"), null);
        ArgumentCaptor<SupervisorActionEntity> cap = ArgumentCaptor.forClass(SupervisorActionEntity.class);
        verify(actions).save(cap.capture());
        assertThat(cap.getValue().getProposal()).contains("target_ids");
        assertThat(cap.getValue().getNarrative()).contains("happened");
    }

    @Test
    void propose_rejectsMalformedJsonStrings() {
        when(actions.existsByActionTypeAndTargetIdsAndStatus(any(), any(), any())).thenReturn(false);
        // unparseable proposal string → loud badRequest, not a silent null
        assertThatThrownBy(() -> service.propose("PRUNE", List.of(1),
                "not json at all", null, null, null, null))
                .isInstanceOf(ApiException.class);
        // valid proposal but unparseable narrative string → also rejected
        assertThatThrownBy(() -> service.propose("PRUNE", List.of(1),
                "{\"target_ids\":[1]}", null, null, "{broken", null))
                .isInstanceOf(ApiException.class);
        // blank / null proposal → required error
        assertThatThrownBy(() -> service.propose("PRUNE", List.of(1),
                "  ", null, null, null, null)).isInstanceOf(ApiException.class);
        assertThatThrownBy(() -> service.propose("PRUNE", List.of(1),
                null, null, null, null, null)).isInstanceOf(ApiException.class);
    }

    // ── manual-trigger clear-pending ────────────────────────────────────

    @Test
    void clearPending_bulkRejectsAllProposedWithFixedReason() {
        SupervisorActionEntity a = action(60L, "PRUNE", "{\"target_ids\":[1]}");
        SupervisorActionEntity b = action(61L, "CFG", "{\"file\":\"x\"}");
        when(actions.findByStatus("proposed")).thenReturn(List.of(a, b));

        int cleared = service.clearPending(99L);

        assertThat(cleared).isEqualTo(2);
        for (SupervisorActionEntity e : List.of(a, b)) {
            assertThat(e.getStatus()).isEqualTo("rejected");
            assertThat(e.getReviewedBy()).isEqualTo(99L);
            assertThat(e.getReviewedAt()).isNotNull();
            assertThat(e.getRejectReason())
                    .isEqualTo(SupervisorCurationService.CLEAR_PENDING_REASON);
        }
        verify(actions).saveAll(List.of(a, b));
        verify(knowledge, never()).save(any());   // audit-only, like reject()
        verify(docMemos, never()).save(any());
    }

    @Test
    void clearPending_emptyQueueReturnsZero() {
        when(actions.findByStatus("proposed")).thenReturn(List.of());
        assertThat(service.clearPending(99L)).isZero();
        verify(actions).saveAll(List.of());
    }

    // ── W3: open-proposals queue ────────────────────────────────────────

    @Test
    void openProposals_returnsSlimRowsForProposedNotSuperseded() {
        SupervisorActionEntity a = action(40L, "CFG", "{\"file\":\"sidecar/.env\"}");
        a.setNarrative("{\"happened\":\"provider cache dead\"}");
        when(actions.findByStatusAndSupersededByIsNullOrderByIdDesc("proposed"))
                .thenReturn(List.of(a));

        List<Map<String, Object>> out = service.openProposals();

        assertThat(out).hasSize(1);
        assertThat(out.get(0)).containsKeys("id", "action_type", "narrative", "proposal", "created_at");
        assertThat(out.get(0).get("action_type")).isEqualTo("CFG");
        assertThat(out.get(0).get("proposal")).isEqualTo(Map.of("file", "sidecar/.env"));
        assertThat(out.get(0).get("narrative")).isEqualTo(Map.of("happened", "provider cache dead"));
    }

    // ── W3: CFG / ISSUE manual-landing semantics ────────────────────────

    @Test
    void propose_acceptsCfgAndIssueWithFreeFormProposal() {
        when(actions.existsByActionTypeAndTargetIdsAndStatus(any(), any(), any())).thenReturn(false);
        assertThat(service.propose("CFG", List.of(),
                Map.of("file", "sidecar/.env", "change", "OLLAMA_MODEL=glm-5.2"),
                null, null, null, null)).containsEntry("deduped", false);
        assertThat(service.propose("ISSUE", List.of(),
                Map.of("title", "bar_chart order flaky", "severity", "med"),
                null, null, null, null)).containsEntry("deduped", false);
        verify(knowledge, never()).save(any());   // stored as-is, no target validation
    }

    @Test
    void approve_cfg_skipsCommitAndKeepsLandedNull() {
        SupervisorActionEntity a = action(20L, "CFG",
                "{\"file\":\"sidecar/.env\",\"change\":\"OLLAMA_MODEL=glm-5.2\"}");
        when(actions.findById(20L)).thenReturn(Optional.of(a));

        Map<String, Object> dto = service.approve(20L, 99L);

        assertThat(dto.get("status")).isEqualTo("approved");
        assertThat(dto.get("reviewed_by")).isEqualTo(99L);
        assertThat(dto.get("landed_at")).isNull();   // human lands later, outside the system
        assertThat(dto.get("landed_by")).isNull();
        @SuppressWarnings("unchecked")
        Map<String, Object> result = (Map<String, Object>) dto.get("commit_result");
        assertThat(result.get("note")).isEqualTo("awaiting manual landing");
        verify(knowledge, never()).save(any());   // nothing committed
        verify(knowledge, never()).findById(any());
        verify(docMemos, never()).save(any());
    }

    @Test
    void approve_issue_behavesLikeCfg() {
        SupervisorActionEntity a = action(21L, "ISSUE", "{\"title\":\"flaky bar_chart\"}");
        when(actions.findById(21L)).thenReturn(Optional.of(a));

        Map<String, Object> dto = service.approve(21L, 99L);

        assertThat(dto.get("status")).isEqualTo("approved");
        assertThat(dto.get("landed_at")).isNull();
        verify(knowledge, never()).save(any());
    }

    // ── W3: supersede on propose ────────────────────────────────────────

    @Test
    void propose_supersedes_marksOldProposedRow() {
        when(actions.existsByActionTypeAndTargetIdsAndStatus(any(), any(), any())).thenReturn(false);
        SupervisorActionEntity old = action(5L, "PRUNE", "{\"target_ids\":[1]}");
        when(actions.findById(5L)).thenReturn(Optional.of(old));

        Map<String, Object> out = service.propose("PRUNE", List.of(1),
                Map.of("target_ids", List.of(1), "v", 2), null, null, null, 5L);

        assertThat(out.get("id")).isEqualTo(77L);
        assertThat(old.getSupersededBy()).isEqualTo(77L);
        verify(actions, times(2)).save(any());   // new proposal + old row stamp
    }

    @Test
    void propose_supersedes_skipsReviewedOrMissingOld() {
        when(actions.existsByActionTypeAndTargetIdsAndStatus(any(), any(), any())).thenReturn(false);
        SupervisorActionEntity reviewed = action(6L, "PRUNE", "{\"target_ids\":[1]}");
        reviewed.setStatus("approved");
        when(actions.findById(6L)).thenReturn(Optional.of(reviewed));
        when(actions.findById(404L)).thenReturn(Optional.empty());

        service.propose("PRUNE", List.of(1), Map.of("v", 1), null, null, null, 6L);
        service.propose("CFG", List.of(), Map.of("v", 2), null, null, null, 404L);

        assertThat(reviewed.getSupersededBy()).isNull();   // reviewed history untouched
        verify(actions, times(2)).save(any());             // only the two new proposals
    }

    // ── W3: post-landing verify ─────────────────────────────────────────

    @Test
    void verifyQueue_returnsSlimRowsForLandedUnverified() {
        SupervisorActionEntity a = action(30L, "PRUNE", "{\"target_ids\":[1,2]}");
        a.setTargetIds("[1,2]");
        a.setLandedAt(java.time.OffsetDateTime.now().minusDays(10));
        when(actions.findByVerifyAtIsNullAndLandedAtBeforeOrderByLandedAtAsc(any()))
                .thenReturn(List.of(a));

        List<Map<String, Object>> queue = service.verifyQueue();

        assertThat(queue).hasSize(1);
        assertThat(queue.get(0)).containsKeys(
                "id", "action_type", "target_ids", "proposal", "narrative", "landed_at");
        assertThat(queue.get(0).get("target_ids")).isEqualTo(List.of(1, 2));
        // cutoff passed to the repo is ~7 days back (grace period)
        ArgumentCaptor<java.time.OffsetDateTime> cap =
                ArgumentCaptor.forClass(java.time.OffsetDateTime.class);
        verify(actions).findByVerifyAtIsNullAndLandedAtBeforeOrderByLandedAtAsc(cap.capture());
        assertThat(cap.getValue()).isBetween(
                java.time.OffsetDateTime.now().minusDays(7).minusMinutes(1),
                java.time.OffsetDateTime.now().minusDays(7).plusMinutes(1));
    }

    @Test
    void verify_stampsResultOnce() {
        SupervisorActionEntity a = action(31L, "PRUNE", "{\"target_ids\":[1]}");
        a.setLandedAt(java.time.OffsetDateTime.now().minusDays(10));
        when(actions.findById(31L)).thenReturn(Optional.of(a));

        Map<String, Object> dto = service.verify(31L, "prune held; no re-pollution observed");

        assertThat(dto.get("verify_result")).isEqualTo("prune held; no re-pollution observed");
        assertThat(dto.get("verify_at")).isNotNull();
    }

    @Test
    void verify_rejectsSecondVerifyAndUnlanded() {
        SupervisorActionEntity verified = action(32L, "PRUNE", "{\"target_ids\":[1]}");
        verified.setLandedAt(java.time.OffsetDateTime.now().minusDays(10));
        verified.setVerifyAt(java.time.OffsetDateTime.now().minusDays(1));
        when(actions.findById(32L)).thenReturn(Optional.of(verified));
        SupervisorActionEntity unlanded = action(33L, "CFG", "{\"file\":\"x\"}");
        when(actions.findById(33L)).thenReturn(Optional.of(unlanded));

        assertThatThrownBy(() -> service.verify(32L, "again")).isInstanceOf(ApiException.class);
        assertThatThrownBy(() -> service.verify(33L, "ok")).isInstanceOf(ApiException.class);
        assertThatThrownBy(() -> service.verify(31L, "  ")).isInstanceOf(ApiException.class);
    }
}
