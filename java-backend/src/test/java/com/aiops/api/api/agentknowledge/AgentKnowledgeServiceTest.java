package com.aiops.api.api.agentknowledge;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Role;
import com.aiops.api.common.ApiException;
import com.aiops.api.domain.agentknowledge.AgentDirectiveFireRepository;
import com.aiops.api.domain.agentknowledge.AgentDirectiveRepository;
import com.aiops.api.domain.agentknowledge.AgentExampleRepository;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeEntity;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeRepository;
import com.aiops.api.domain.agentknowledge.AgentLexiconRepository;
import com.aiops.api.domain.agentknowledge.BlockDocMemoRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.time.OffsetDateTime;
import java.util.Optional;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * Pure-Mockito tests — V75 knowledge governance: ON_DUTY creates drafts
 * (fail-closed on empty roles), the active toggle keeps status coherent and
 * never silently activates a draft, and approve is the only draft → active
 * path.
 */
class AgentKnowledgeServiceTest {

    private AgentKnowledgeRepository knowledge;
    private AgentKnowledgeService service;

    private static final AuthPrincipal ON_DUTY = new AuthPrincipal(1L, "duty", Set.of(Role.ON_DUTY));
    private static final AuthPrincipal NO_ROLES = new AuthPrincipal(1L, "ghost", Set.of());
    private static final AuthPrincipal PE = new AuthPrincipal(1L, "pe", Set.of(Role.PE));
    private static final AuthPrincipal ADMIN = new AuthPrincipal(1L, "admin", Set.of(Role.IT_ADMIN));
    private static final AuthPrincipal OTHER_PE = new AuthPrincipal(2L, "pe2", Set.of(Role.PE));

    @BeforeEach
    void setUp() {
        knowledge = mock(AgentKnowledgeRepository.class);
        service = new AgentKnowledgeService(
                mock(AgentDirectiveRepository.class),
                mock(AgentDirectiveFireRepository.class),
                mock(AgentLexiconRepository.class),
                knowledge,
                mock(AgentExampleRepository.class),
                mock(BlockDocMemoRepository.class));
        when(knowledge.save(any())).thenAnswer(inv -> {
            AgentKnowledgeEntity e = inv.getArgument(0);
            if (e.getId() == null) e.setId(500L);
            return e;
        });
    }

    private static Dtos.CreateKnowledgeRequest createReq() {
        return new Dtos.CreateKnowledgeRequest("global", null, "SPC 慣例", "OOC 看最近 5 筆", null);
    }

    private AgentKnowledgeEntity row(long id, Long ownerId, String status, boolean active) {
        AgentKnowledgeEntity e = new AgentKnowledgeEntity();
        e.setId(id);
        e.setUserId(ownerId);
        e.setStatus(status);
        e.setActive(active);
        e.setTitle("t");
        e.setBody("b");
        return e;
    }

    // ── create: role-gated lifecycle ────────────────────────────────────

    @Test
    void create_onDutyOnly_forcesDraftInactive() {
        Dtos.KnowledgeDto dto = service.createKnowledge(createReq(), ON_DUTY);
        assertThat(dto.status()).isEqualTo("draft");
        assertThat(dto.active()).isFalse();
    }

    @Test
    void create_emptyRoles_failsClosedToDraft() {
        Dtos.KnowledgeDto dto = service.createKnowledge(createReq(), NO_ROLES);
        assertThat(dto.status()).isEqualTo("draft");
        assertThat(dto.active()).isFalse();
    }

    @Test
    void create_peOrAdmin_publishesActive() {
        assertThat(service.createKnowledge(createReq(), PE).status()).isEqualTo("active");
        assertThat(service.createKnowledge(createReq(), ADMIN).status()).isEqualTo("active");
        assertThat(service.createKnowledge(createReq(), PE).active()).isTrue();
    }

    // ── approve: the only draft → active path ───────────────────────────

    @Test
    void approve_draft_activates() {
        when(knowledge.findById(10L)).thenReturn(Optional.of(row(10, 1L, "draft", false)));
        Dtos.KnowledgeDto dto = service.approveKnowledge(10L, PE);
        assertThat(dto.status()).isEqualTo("active");
        assertThat(dto.active()).isTrue();
    }

    // ── W3: review_at backfill (domain | procedure only) ────────────────

    @Test
    void approve_domainDraft_backfillsReviewAt365d() {
        AgentKnowledgeEntity draft = row(20, 1L, "draft", false);
        draft.setMemoClass("domain");
        when(knowledge.findById(20L)).thenReturn(Optional.of(draft));

        Dtos.KnowledgeDto dto = service.approveKnowledge(20L, PE);

        assertThat(dto.reviewAt()).isNotNull();
        assertThat(dto.reviewAt()).isBetween(
                OffsetDateTime.now().plusDays(365).minusMinutes(1),
                OffsetDateTime.now().plusDays(365).plusMinutes(1));
    }

    @Test
    void approve_procedureDraft_backfillsReviewAt() {
        AgentKnowledgeEntity draft = row(21, 1L, "draft", false);
        draft.setMemoClass("procedure");
        when(knowledge.findById(21L)).thenReturn(Optional.of(draft));
        assertThat(service.approveKnowledge(21L, PE).reviewAt()).isNotNull();
    }

    @Test
    void approve_nonDurableOrUnclassifiedDraft_noReviewAt() {
        AgentKnowledgeEntity episodic = row(22, 1L, "draft", false);
        episodic.setMemoClass("episodic");
        when(knowledge.findById(22L)).thenReturn(Optional.of(episodic));
        AgentKnowledgeEntity legacy = row(23, 1L, "draft", false);   // memo_class NULL
        when(knowledge.findById(23L)).thenReturn(Optional.of(legacy));

        assertThat(service.approveKnowledge(22L, PE).reviewAt()).isNull();
        assertThat(service.approveKnowledge(23L, PE).reviewAt()).isNull();
    }

    @Test
    void approve_existingReviewAt_notOverwritten() {
        AgentKnowledgeEntity draft = row(24, 1L, "draft", false);
        draft.setMemoClass("domain");
        OffsetDateTime preset = OffsetDateTime.now().plusDays(30);
        draft.setReviewAt(preset);
        when(knowledge.findById(24L)).thenReturn(Optional.of(draft));

        assertThat(service.approveKnowledge(24L, PE).reviewAt()).isEqualTo(preset);
    }

    @Test
    void create_uiPath_hasNoMemoClass_soNoReviewAt() {
        // UI create requests carry no memo_class → the backfill guard must not fire
        assertThat(service.createKnowledge(createReq(), PE).reviewAt()).isNull();
    }

    @Test
    void approve_nonDraft_rejected() {
        when(knowledge.findById(11L)).thenReturn(Optional.of(row(11, 1L, "active", true)));
        when(knowledge.findById(12L)).thenReturn(Optional.of(row(12, 1L, "archived", false)));
        assertThatThrownBy(() -> service.approveKnowledge(11L, PE)).isInstanceOf(ApiException.class);
        assertThatThrownBy(() -> service.approveKnowledge(12L, PE)).isInstanceOf(ApiException.class);
    }

    @Test
    void approve_crossUser_peApprovesAnotherUsersDraft() {
        // ON_DUTY (user 42) submitted; PE (user 2) reviews — the role gate IS
        // the authorization, no owner check.
        AgentKnowledgeEntity draft = row(13, 42L, "draft", false);
        when(knowledge.findById(13L)).thenReturn(Optional.of(draft));
        Dtos.KnowledgeDto dto = service.approveKnowledge(13L, OTHER_PE);
        assertThat(dto.status()).isEqualTo("active");
        assertThat(dto.active()).isTrue();
        assertThat(dto.userId()).isEqualTo(42L);   // owner unchanged, on the wire as user_id
    }

    @Test
    void approve_onDutyOrNoRoles_forbidden() {
        when(knowledge.findById(14L)).thenReturn(Optional.of(row(14, 1L, "draft", false)));
        assertThatThrownBy(() -> service.approveKnowledge(14L, ON_DUTY))
                .isInstanceOf(ApiException.class);
        assertThatThrownBy(() -> service.approveKnowledge(14L, NO_ROLES))
                .isInstanceOf(ApiException.class);
    }

    // ── drafts review queue (cross-user) ────────────────────────────────

    @Test
    void listDrafts_returnsAllUsersDrafts_forPe() {
        when(knowledge.findByStatusOrderByCreatedAtDesc("draft"))
                .thenReturn(java.util.List.of(row(30, 1L, "draft", false), row(31, 42L, "draft", false)));
        var drafts = service.listDrafts(PE);
        assertThat(drafts).hasSize(2);
        assertThat(drafts.get(1).userId()).isEqualTo(42L);   // submitter surfaces as user_id
    }

    @Test
    void listDrafts_onDutyOrNoRoles_forbidden() {
        assertThatThrownBy(() -> service.listDrafts(ON_DUTY)).isInstanceOf(ApiException.class);
        assertThatThrownBy(() -> service.listDrafts(NO_ROLES)).isInstanceOf(ApiException.class);
        verify(knowledge, never()).findByStatusOrderByCreatedAtDesc(any());
    }

    // ── active toggle keeps status coherent ─────────────────────────────

    private static Dtos.PatchKnowledgeRequest toggle(Boolean active) {
        return new Dtos.PatchKnowledgeRequest(null, null, null, null, null, active);
    }

    @Test
    void toggle_enable_refusesDraft() {
        when(knowledge.findById(20L)).thenReturn(Optional.of(row(20, 1L, "draft", false)));
        assertThatThrownBy(() -> service.patchKnowledge(20L, toggle(true), PE))
                .isInstanceOf(ApiException.class);
    }

    @Test
    void toggle_disable_archivesActiveRow() {
        AgentKnowledgeEntity e = row(21, 1L, "active", true);
        when(knowledge.findById(21L)).thenReturn(Optional.of(e));
        service.patchKnowledge(21L, toggle(false), PE);
        assertThat(e.getActive()).isFalse();
        assertThat(e.getStatus()).isEqualTo("archived");
    }

    @Test
    void toggle_disable_keepsDraftStatus() {
        AgentKnowledgeEntity e = row(22, 1L, "draft", false);
        when(knowledge.findById(22L)).thenReturn(Optional.of(e));
        service.patchKnowledge(22L, toggle(false), PE);
        assertThat(e.getStatus()).isEqualTo("draft");   // disable never rewrites a draft
    }

    @Test
    void toggle_enable_reactivatesArchivedRow() {
        AgentKnowledgeEntity e = row(23, 1L, "archived", false);
        when(knowledge.findById(23L)).thenReturn(Optional.of(e));
        service.patchKnowledge(23L, toggle(true), PE);
        assertThat(e.getActive()).isTrue();
        assertThat(e.getStatus()).isEqualTo("active");
    }

    @Test
    void create_draftAppearsInDtoOnSavedEntity() {
        ArgumentCaptor<AgentKnowledgeEntity> cap = ArgumentCaptor.forClass(AgentKnowledgeEntity.class);
        service.createKnowledge(createReq(), ON_DUTY);
        verify(knowledge).save(cap.capture());
        assertThat(cap.getValue().getStatus()).isEqualTo("draft");
        assertThat(cap.getValue().getActive()).isFalse();
        assertThat(cap.getValue().getWrittenBy()).isEqualTo("human");
    }
}
