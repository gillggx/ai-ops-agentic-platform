package com.aiops.api.api.memory;

import com.aiops.api.domain.agentknowledge.AgentKnowledgeRepository;
import org.junit.jupiter.api.Test;

import java.time.OffsetDateTime;
import java.time.ZoneOffset;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;

/**
 * Pure-Mockito tests — W3 lifecycle janitor. Date math lives in
 * {@link MemoryGovernancePolicy} (pure); the janitor test pins {@code now}
 * and verifies the repository receives EXACTLY the policy cutoffs.
 */
class MemoryLifecycleJanitorTest {

    private static final OffsetDateTime NOW =
            OffsetDateTime.of(2026, 7, 6, 3, 20, 0, 0, ZoneOffset.UTC);

    // ── policy date math (pure) ─────────────────────────────────────────

    @Test
    void policy_draftArchiveCutoff_is30DaysBack() {
        assertThat(MemoryGovernancePolicy.draftArchiveCutoff(NOW))
                .isEqualTo(NOW.minusDays(30));
    }

    @Test
    void policy_episodicStaleCutoff_is90DaysBack() {
        assertThat(MemoryGovernancePolicy.episodicStaleCutoff(NOW))
                .isEqualTo(NOW.minusDays(90));
    }

    @Test
    void policy_nextReviewAt_is365DaysAhead() {
        assertThat(MemoryGovernancePolicy.nextReviewAt(NOW))
                .isEqualTo(NOW.plusDays(365));
    }

    @Test
    void policy_requiresReview_onlyDurableClasses() {
        assertThat(MemoryGovernancePolicy.requiresReview("domain")).isTrue();
        assertThat(MemoryGovernancePolicy.requiresReview("procedure")).isTrue();
        assertThat(MemoryGovernancePolicy.requiresReview("episodic")).isFalse();
        assertThat(MemoryGovernancePolicy.requiresReview("preference")).isFalse();
        assertThat(MemoryGovernancePolicy.requiresReview(null)).isFalse();
    }

    // ── janitor wiring ──────────────────────────────────────────────────

    @Test
    void runOnce_callsBothBulkUpdatesWithPolicyCutoffs() {
        AgentKnowledgeRepository repo = mock(AgentKnowledgeRepository.class);
        when(repo.archiveExpiredDrafts(NOW.minusDays(30))).thenReturn(3);
        when(repo.staleExpiredEpisodic(NOW.minusDays(90))).thenReturn(5);

        new MemoryLifecycleJanitor(repo).runOnce(NOW);

        verify(repo).archiveExpiredDrafts(NOW.minusDays(30));
        verify(repo).staleExpiredEpisodic(NOW.minusDays(90));
        verifyNoMoreInteractions(repo);   // deterministic: exactly two bulk UPDATEs
    }

    @Test
    void runOnce_zeroMatchesStillCompletes() {
        AgentKnowledgeRepository repo = mock(AgentKnowledgeRepository.class);
        when(repo.archiveExpiredDrafts(NOW.minusDays(30))).thenReturn(0);
        when(repo.staleExpiredEpisodic(NOW.minusDays(90))).thenReturn(0);

        new MemoryLifecycleJanitor(repo).runOnce(NOW);

        verify(repo).archiveExpiredDrafts(NOW.minusDays(30));
        verify(repo).staleExpiredEpisodic(NOW.minusDays(90));
    }
}
