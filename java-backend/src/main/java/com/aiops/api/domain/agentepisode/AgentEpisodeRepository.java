package com.aiops.api.domain.agentepisode;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

import java.util.Optional;

public interface AgentEpisodeRepository extends JpaRepository<AgentEpisodeEntity, Long> {

    Optional<AgentEpisodeEntity> findByEpisodeKey(String episodeKey);

    List<AgentEpisodeEntity> findAllByOrderByIdDesc(Pageable pageable);

    /** Monitor (V73): self-assessed-OK-but-user-rejected builds in window. */
    long countByDivergenceTrueAndStartedAtAfter(java.time.OffsetDateTime cutoff);

    long countByStartedAtAfter(java.time.OffsetDateTime cutoff);
}
