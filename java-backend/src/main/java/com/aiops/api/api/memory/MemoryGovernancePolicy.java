package com.aiops.api.api.memory;

import java.time.OffsetDateTime;

/**
 * W3 memory-governance policy constants + pure date math.
 *
 * <p>Single source of the lifecycle windows used by
 * {@link MemoryLifecycleJanitor} (draft archiving, episodic staleness) and
 * the review_at backfill in {@code AgentKnowledgeService}.
 *
 * <p>SYNC DUTY: the Python sidecar mirrors these constants (memory-layer
 * governance module). If a window changes here it MUST change there in the
 * same commit — the sidecar has no runtime view of this class.
 */
public final class MemoryGovernancePolicy {

    /** Drafts nobody approved within this window get archived. */
    public static final int DRAFT_ARCHIVE_DAYS = 30;

    /** Active episodic rows unused for this long go stale (out of retrieval). */
    public static final int EPISODIC_STALE_DAYS = 90;

    /** Preference rows unused for this long are prune candidates
     *  (consumed by the sidecar proposer — no janitor rule here yet). */
    public static final int PREFERENCE_PRUNE_DAYS = 180;

    /** Annual review period for durable domain / procedure rows. */
    public static final int REVIEW_PERIOD_DAYS = 365;

    private MemoryGovernancePolicy() {}

    /** created_at cutoff: drafts older than this get archived. */
    public static OffsetDateTime draftArchiveCutoff(OffsetDateTime now) {
        return now.minusDays(DRAFT_ARCHIVE_DAYS);
    }

    /** COALESCE(last_used_at, created_at) cutoff: episodic rows older go stale. */
    public static OffsetDateTime episodicStaleCutoff(OffsetDateTime now) {
        return now.minusDays(EPISODIC_STALE_DAYS);
    }

    /** review_at value stamped on new/approved domain|procedure rows. */
    public static OffsetDateTime nextReviewAt(OffsetDateTime now) {
        return now.plusDays(REVIEW_PERIOD_DAYS);
    }

    /** True for the memo classes that carry an annual review date. */
    public static boolean requiresReview(String memoClass) {
        return "domain".equals(memoClass) || "procedure".equals(memoClass);
    }
}
