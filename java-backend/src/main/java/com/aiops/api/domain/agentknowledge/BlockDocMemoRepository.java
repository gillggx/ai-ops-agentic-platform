package com.aiops.api.domain.agentknowledge;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface BlockDocMemoRepository extends JpaRepository<BlockDocMemoEntity, Long> {

    /** Dedup: one memo per (block, param, episode). */
    boolean existsByBlockIdAndParamAndFromEpisode(String blockId, String param, String fromEpisode);

    long countByStatus(String status);

    /** Newest-first, capped — for the /agent-knowledge Builder-memory view. */
    List<BlockDocMemoEntity> findTop200ByOrderByIdDesc();
}
