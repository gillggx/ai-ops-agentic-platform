package com.aiops.api.api.internal;

import com.aiops.api.domain.agentknowledge.AgentKnowledgeEntity;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * W3 weighted knowledge re-ranking — pure functions, no Spring, no I/O.
 *
 * <p>score = cosineSimilarity × priorityWeight × freshnessWeight, where
 * <ul>
 *   <li>priorityWeight: high 1.0 / med 0.85 / low 0.7 (unknown → med);</li>
 *   <li>freshnessWeight: half-life {@value #FRESHNESS_HALF_LIFE_DAYS} days on
 *       max(createdAt, lastUsedAt) — {@code 0.5^(ageDays/180)}, floored at
 *       {@value #FRESHNESS_FLOOR} so old-but-relevant rows never vanish.</li>
 * </ul>
 *
 * <p>After scoring, a per-class quota caps noisy classes in the final top-K:
 * at most one 'preference' and one 'episodic' row — overflow slots go to the
 * next-best candidate of any other class.
 *
 * <p>Behind the {@code aiops.knowledge.weighted-ranking} flag (default OFF)
 * in {@link InternalAgentKnowledgeService} — flag OFF never reaches this class.
 */
public final class KnowledgeReRanker {

    public static final double PRIORITY_WEIGHT_HIGH = 1.0;
    public static final double PRIORITY_WEIGHT_MED = 0.85;
    public static final double PRIORITY_WEIGHT_LOW = 0.7;

    public static final double FRESHNESS_HALF_LIFE_DAYS = 180.0;
    public static final double FRESHNESS_FLOOR = 0.25;

    public static final int PREFERENCE_QUOTA = 1;
    public static final int EPISODIC_QUOTA = 1;

    private static final double SECONDS_PER_DAY = 86_400.0;

    private KnowledgeReRanker() {}

    /** One retrieval candidate: the row + its cosine similarity (1 - dist). */
    public record Candidate(AgentKnowledgeEntity entity, double similarity) {}

    /**
     * Re-rank {@code candidates} by weighted score and return the top-K
     * entities after applying the per-class quota. Sort is stable, so ties
     * keep the incoming (cosine) order.
     */
    public static List<AgentKnowledgeEntity> rerank(List<Candidate> candidates,
                                                    int topK, OffsetDateTime now) {
        if (candidates == null || candidates.isEmpty() || topK <= 0) {
            return List.of();
        }
        List<Candidate> byScore = candidates.stream()
                .sorted(Comparator.comparingDouble((Candidate c) -> score(c, now)).reversed())
                .toList();
        List<AgentKnowledgeEntity> out = new ArrayList<>(topK);
        int preferenceCount = 0;
        int episodicCount = 0;
        for (Candidate c : byScore) {
            String memoClass = c.entity().getMemoClass();
            if ("preference".equals(memoClass)) {
                if (preferenceCount >= PREFERENCE_QUOTA) continue;
                preferenceCount++;
            } else if ("episodic".equals(memoClass)) {
                if (episodicCount >= EPISODIC_QUOTA) continue;
                episodicCount++;
            }
            out.add(c.entity());
            if (out.size() >= topK) break;
        }
        return out;
    }

    /** Weighted score for one candidate — exposed for tests. */
    static double score(Candidate c, OffsetDateTime now) {
        AgentKnowledgeEntity e = c.entity();
        return c.similarity()
                * priorityWeight(e.getPriority())
                * freshnessWeight(e.getCreatedAt(), e.getLastUsedAt(), now);
    }

    static double priorityWeight(String priority) {
        if ("high".equalsIgnoreCase(priority)) return PRIORITY_WEIGHT_HIGH;
        if ("low".equalsIgnoreCase(priority)) return PRIORITY_WEIGHT_LOW;
        return PRIORITY_WEIGHT_MED;   // 'med' and anything unexpected
    }

    /** Exponential decay with a floor. Reference time is the freshest of
     *  createdAt / lastUsedAt; rows with neither timestamp count as fresh
     *  (weight 1.0) rather than being nuked by a bogus infinite age. */
    static double freshnessWeight(OffsetDateTime createdAt, OffsetDateTime lastUsedAt,
                                  OffsetDateTime now) {
        OffsetDateTime reference = maxOf(createdAt, lastUsedAt);
        if (reference == null) return 1.0;
        double ageDays = Math.max(0.0,
                Duration.between(reference, now).getSeconds() / SECONDS_PER_DAY);
        double weight = Math.pow(0.5, ageDays / FRESHNESS_HALF_LIFE_DAYS);
        return Math.max(FRESHNESS_FLOOR, weight);
    }

    private static OffsetDateTime maxOf(OffsetDateTime a, OffsetDateTime b) {
        if (a == null) return b;
        if (b == null) return a;
        return a.isAfter(b) ? a : b;
    }
}
