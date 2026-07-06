package com.aiops.api.api.internal;

import com.aiops.api.api.internal.KnowledgeReRanker.Candidate;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeEntity;
import org.junit.jupiter.api.Test;

import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.offset;

/**
 * Pure unit tests — W3 weighted re-ranker. No mocks needed: the class is
 * side-effect free by design.
 */
class KnowledgeReRankerTest {

    private static final OffsetDateTime NOW =
            OffsetDateTime.of(2026, 7, 6, 12, 0, 0, 0, ZoneOffset.UTC);

    private static AgentKnowledgeEntity row(long id, String priority, String memoClass,
                                            OffsetDateTime createdAt, OffsetDateTime lastUsedAt) {
        AgentKnowledgeEntity e = new AgentKnowledgeEntity();
        e.setId(id);
        e.setPriority(priority);
        e.setMemoClass(memoClass);
        e.setCreatedAt(createdAt);
        e.setLastUsedAt(lastUsedAt);
        return e;
    }

    private static Candidate cand(long id, double sim, String priority, String memoClass,
                                  OffsetDateTime createdAt, OffsetDateTime lastUsedAt) {
        return new Candidate(row(id, priority, memoClass, createdAt, lastUsedAt), sim);
    }

    // ── component weights ───────────────────────────────────────────────

    @Test
    void priorityWeights_matchSpec() {
        assertThat(KnowledgeReRanker.priorityWeight("high")).isEqualTo(1.0);
        assertThat(KnowledgeReRanker.priorityWeight("med")).isEqualTo(0.85);
        assertThat(KnowledgeReRanker.priorityWeight("low")).isEqualTo(0.7);
        assertThat(KnowledgeReRanker.priorityWeight(null)).isEqualTo(0.85);   // unknown → med
        assertThat(KnowledgeReRanker.priorityWeight("weird")).isEqualTo(0.85);
    }

    @Test
    void freshness_halfLifeAt180Days() {
        double w = KnowledgeReRanker.freshnessWeight(NOW.minusDays(180), null, NOW);
        assertThat(w).isCloseTo(0.5, offset(1e-9));
    }

    @Test
    void freshness_brandNewIsOne_andFloorAt025() {
        assertThat(KnowledgeReRanker.freshnessWeight(NOW, null, NOW)).isEqualTo(1.0);
        // 5 years old → raw 0.5^(1825/180) ≈ 0.00088, floored
        assertThat(KnowledgeReRanker.freshnessWeight(NOW.minusDays(1825), null, NOW))
                .isEqualTo(KnowledgeReRanker.FRESHNESS_FLOOR);
    }

    @Test
    void freshness_usesFresherOfCreatedAndLastUsed() {
        // created 400d ago but used yesterday →近乎全新
        double w = KnowledgeReRanker.freshnessWeight(
                NOW.minusDays(400), NOW.minusDays(1), NOW);
        assertThat(w).isGreaterThan(0.99);
        // both null → treated as fresh, not infinitely old
        assertThat(KnowledgeReRanker.freshnessWeight(null, null, NOW)).isEqualTo(1.0);
    }

    // ── ordering ────────────────────────────────────────────────────────

    @Test
    void rerank_priorityOutweighsSlightlyBetterCosine() {
        // low-priority row wins on cosine (0.90) but high-priority (0.80) wins
        // weighted: 0.90*0.7=0.63 < 0.80*1.0=0.80 (both fresh).
        Candidate lowPri = cand(1, 0.90, "low", "domain", NOW, null);
        Candidate highPri = cand(2, 0.80, "high", "domain", NOW, null);

        List<AgentKnowledgeEntity> out =
                KnowledgeReRanker.rerank(List.of(lowPri, highPri), 2, NOW);

        assertThat(out).extracting(AgentKnowledgeEntity::getId).containsExactly(2L, 1L);
    }

    @Test
    void rerank_staleRowDropsBelowFreshRow() {
        // same cosine + priority; 360d-old (0.25 raw, above floor) loses to fresh
        Candidate stale = cand(1, 0.9, "med", "domain", NOW.minusDays(360), null);
        Candidate fresh = cand(2, 0.9, "med", "domain", NOW, null);

        List<AgentKnowledgeEntity> out =
                KnowledgeReRanker.rerank(List.of(stale, fresh), 2, NOW);

        assertThat(out).extracting(AgentKnowledgeEntity::getId).containsExactly(2L, 1L);
    }

    @Test
    void rerank_topKTruncates() {
        List<Candidate> cands = List.of(
                cand(1, 0.9, "high", "domain", NOW, null),
                cand(2, 0.8, "high", "domain", NOW, null),
                cand(3, 0.7, "high", "domain", NOW, null));
        assertThat(KnowledgeReRanker.rerank(cands, 2, NOW)).hasSize(2);
        assertThat(KnowledgeReRanker.rerank(List.of(), 3, NOW)).isEmpty();
        assertThat(KnowledgeReRanker.rerank(cands, 0, NOW)).isEmpty();
    }

    // ── per-class quota ─────────────────────────────────────────────────

    @Test
    void rerank_quotaCapsPreferenceAndEpisodicAtOneEach() {
        List<Candidate> cands = List.of(
                cand(1, 0.99, "high", "preference", NOW, null),
                cand(2, 0.98, "high", "preference", NOW, null),   // over quota → replaced
                cand(3, 0.97, "high", "episodic", NOW, null),
                cand(4, 0.96, "high", "episodic", NOW, null),     // over quota → replaced
                cand(5, 0.50, "low", "domain", NOW.minusDays(360), null),
                cand(6, 0.40, "low", "domain", NOW.minusDays(360), null));

        List<AgentKnowledgeEntity> out = KnowledgeReRanker.rerank(cands, 4, NOW);

        // best preference + best episodic kept; overflow slots go to next-best domain rows
        assertThat(out).extracting(AgentKnowledgeEntity::getId)
                .containsExactly(1L, 3L, 5L, 6L);
    }

    @Test
    void rerank_quotaDoesNotApplyToOtherClasses() {
        List<Candidate> cands = List.of(
                cand(1, 0.9, "high", "domain", NOW, null),
                cand(2, 0.8, "high", "domain", NOW, null),
                cand(3, 0.7, "high", null, NOW, null));   // legacy unclassified → no quota

        assertThat(KnowledgeReRanker.rerank(cands, 3, NOW))
                .extracting(AgentKnowledgeEntity::getId).containsExactly(1L, 2L, 3L);
    }

    @Test
    void rerank_quotaOverflowStillFillsTopK() {
        // 3 preferences + 1 domain, topK=2 → 1 preference + the domain row
        List<Candidate> cands = List.of(
                cand(1, 0.9, "high", "preference", NOW, null),
                cand(2, 0.8, "high", "preference", NOW, null),
                cand(3, 0.7, "high", "preference", NOW, null),
                cand(4, 0.1, "low", "domain", NOW.minusDays(720), null));

        assertThat(KnowledgeReRanker.rerank(cands, 2, NOW))
                .extracting(AgentKnowledgeEntity::getId).containsExactly(1L, 4L);
    }
}
