package com.aiops.api.api.memory;

import com.aiops.api.domain.agentknowledge.AgentKnowledgeRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;

/**
 * W3 memory-lifecycle janitor — daily, deterministic, ZERO LLM involvement.
 *
 * <p>Two bulk rules over {@code agent_knowledge}
 * (windows in {@link MemoryGovernancePolicy}):
 * <ol>
 *   <li>draft older than {@code DRAFT_ARCHIVE_DAYS} → archived
 *       (nobody approved it; stop cluttering the review queue);</li>
 *   <li>active episodic unused for {@code EPISODIC_STALE_DAYS} → stale
 *       (episodes decay; durable classes are untouched).</li>
 * </ol>
 *
 * <p>Runs in the MAIN API service (not the java-scheduler module): this is
 * pure single-table DB hygiene with no cross-service coordination, and the
 * API JVM is the sole owner of {@code agent_knowledge} writes. The app class
 * re-enables {@code @EnableScheduling} for exactly this bean — see the note
 * on {@link com.aiops.api.AiopsApiApplication}.
 */
@Component
public class MemoryLifecycleJanitor {

    private static final Logger log = LoggerFactory.getLogger(MemoryLifecycleJanitor.class);

    private final AgentKnowledgeRepository knowledge;

    public MemoryLifecycleJanitor(AgentKnowledgeRepository knowledge) {
        this.knowledge = knowledge;
    }

    /** Daily at 03:20 — off-peak, after the sidecar's nightly jobs.
     *  {@code @Transactional} must sit HERE (the proxy entry point) — the
     *  internal {@code runOnce} call is a self-invocation, so an annotation
     *  on it alone would be bypassed and the {@code @Modifying} bulk
     *  updates would run without the required transaction. */
    @Scheduled(cron = "0 20 3 * * *")
    @Transactional
    public void runDaily() {
        runOnce(OffsetDateTime.now());
    }

    /** Deterministic body, split out so tests can pin {@code now}.
     *  {@code @Transactional} kept for direct external callers. */
    @Transactional
    public void runOnce(OffsetDateTime now) {
        int archivedDrafts = knowledge.archiveExpiredDrafts(
                MemoryGovernancePolicy.draftArchiveCutoff(now));
        int staledEpisodic = knowledge.staleExpiredEpisodic(
                MemoryGovernancePolicy.episodicStaleCutoff(now));
        log.info("MemoryLifecycleJanitor: archived {} expired drafts (>{}d), "
                        + "staled {} unused episodic rows (>{}d)",
                archivedDrafts, MemoryGovernancePolicy.DRAFT_ARCHIVE_DAYS,
                staledEpisodic, MemoryGovernancePolicy.EPISODIC_STALE_DAYS);
    }
}
