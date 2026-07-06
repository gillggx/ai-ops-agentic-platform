package com.aiops.api.api.agentepisode;

import com.aiops.api.domain.agentepisode.AgentEpisodeRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;

/**
 * Orphan-episode janitor — deterministic, ZERO LLM.
 *
 * <p>An episode row is created when a build starts and finalized when it ends.
 * If the sidecar process dies mid-build (systemd timeout, OOM, deploy restart),
 * {@code finalize()} never runs and the row is stranded at
 * {@code status='running'} with null {@code finished_at} forever. That pollutes
 * Agent Activity with zombies and makes the trace tab show "無可讀 trace"
 * because no trace_file was ever linked. (Observed 2026-07-06: the sidecar was
 * SIGKILLed by systemd at 16:02 and every in-flight episode was stranded.)
 *
 * <p>This bean sweeps any {@code running} row older than
 * {@link #STALE_RUNNING_MINUTES} minutes into {@code interrupted} + stamps
 * {@code finished_at}. It runs once at startup (to clear rows orphaned by the
 * crash that just restarted us) and every {@link #SWEEP_INTERVAL_MS} ms
 * thereafter. Same-JVM DB hygiene — rides the app's existing
 * {@code @EnableScheduling} (see {@link com.aiops.api.AiopsApiApplication}).
 */
@Component
public class AgentEpisodeJanitor {

    private static final Logger log = LoggerFactory.getLogger(AgentEpisodeJanitor.class);

    /** A real build never runs this long; past it, 'running' means orphaned. */
    static final long STALE_RUNNING_MINUTES = 20;
    /** Periodic re-sweep cadence (10 min). */
    private static final long SWEEP_INTERVAL_MS = 10 * 60 * 1000L;

    private final AgentEpisodeRepository episodes;

    public AgentEpisodeJanitor(AgentEpisodeRepository episodes) {
        this.episodes = episodes;
    }

    /** Clear crash-orphaned rows as soon as the API is up (this JVM may have
     *  just restarted after the very crash that stranded them).
     *  {@code @Transactional} MUST sit on this proxied entry point — the
     *  {@code runOnce} call below is a self-invocation, so an annotation on it
     *  alone would be bypassed and the {@code @Modifying} bulk UPDATE would run
     *  without a transaction (TransactionRequiredException). Same pattern as
     *  {@link com.aiops.api.api.memory.MemoryLifecycleJanitor}. */
    @EventListener(ApplicationReadyEvent.class)
    @Transactional
    public void sweepOnStartup() {
        runOnce(OffsetDateTime.now());
    }

    @Scheduled(fixedDelay = SWEEP_INTERVAL_MS, initialDelay = SWEEP_INTERVAL_MS)
    @Transactional
    public void sweepPeriodic() {
        runOnce(OffsetDateTime.now());
    }

    /** Deterministic body, split out so tests can pin {@code now}.
     *  {@code @Transactional} kept for direct external/test callers. */
    @Transactional
    public int runOnce(OffsetDateTime now) {
        OffsetDateTime cutoff = now.minusMinutes(STALE_RUNNING_MINUTES);
        int marked = episodes.markStaleRunningInterrupted(cutoff, now);
        if (marked > 0) {
            log.info("AgentEpisodeJanitor: marked {} stale 'running' episode(s) "
                    + "(started >{}m ago) as 'interrupted'", marked, STALE_RUNNING_MINUTES);
        }
        return marked;
    }
}
