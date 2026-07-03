package com.aiops.api.domain.agentepisode;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface AgentStepRepository extends JpaRepository<AgentStepEntity, Long> {

    List<AgentStepEntity> findByEpisodeIdOrderByTsAsc(Long episodeId);

    long countByEpisodeId(Long episodeId);

    /** Monitor (V73): repair outcomes in window (payload carries result). */
    long countByEventTypeAndTsAfter(String eventType, java.time.OffsetDateTime cutoff);

    @org.springframework.data.jpa.repository.Query(value = """
            SELECT count(*) FROM agent_steps
            WHERE event_type = 'repair_outcome' AND ts > :cutoff
              AND payload LIKE '%handover%'
            """, nativeQuery = true)
    long countRepairHandoversAfter(@org.springframework.data.repository.query.Param("cutoff") java.time.OffsetDateTime cutoff);
}
