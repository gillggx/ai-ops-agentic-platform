package com.aiops.api.domain.agentepisode;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

import java.util.Optional;

public interface AgentEpisodeRepository extends JpaRepository<AgentEpisodeEntity, Long> {

    Optional<AgentEpisodeEntity> findByEpisodeKey(String episodeKey);

    List<AgentEpisodeEntity> findAllByOrderByIdDesc(Pageable pageable);

    /** Monitor (V73): self-assessed-OK-but-user-rejected builds in window. */
    long countByDivergenceTrueAndStartedAtAfter(java.time.OffsetDateTime cutoff);

    long countByStartedAtAfter(java.time.OffsetDateTime cutoff);

    /**
     * Orphan-episode sweep (2026-07-06): a build whose sidecar process was
     * killed mid-flight (systemd timeout, OOM, deploy restart) never runs its
     * {@code finalize()} — the row is stranded at {@code status='running'} with
     * a null {@code finished_at} forever, so the UI shows "無可讀 trace" and the
     * activity list is polluted with zombies. Mark any {@code running} row that
     * started before the cutoff as {@code interrupted} and stamp finished_at so
     * duration renders. Bulk UPDATE — no LLM, single table. */
    @Modifying
    @Query("UPDATE AgentEpisodeEntity e SET e.status = 'interrupted', "
            + "e.finishedAt = :now WHERE e.status = 'running' "
            + "AND e.startedAt < :cutoff")
    int markStaleRunningInterrupted(@Param("cutoff") java.time.OffsetDateTime cutoff,
                                    @Param("now") java.time.OffsetDateTime now);
}
