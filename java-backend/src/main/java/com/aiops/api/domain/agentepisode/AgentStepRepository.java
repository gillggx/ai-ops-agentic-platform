package com.aiops.api.domain.agentepisode;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface AgentStepRepository extends JpaRepository<AgentStepEntity, Long> {

    List<AgentStepEntity> findByEpisodeIdOrderByTsAsc(Long episodeId);

    long countByEpisodeId(Long episodeId);
}
