package com.aiops.api.domain.agentknowledge;

import org.springframework.data.jpa.repository.JpaRepository;

public interface BlockDocMemoRepository extends JpaRepository<BlockDocMemoEntity, Long> {

    /** Dedup: one memo per (block, param, episode). */
    boolean existsByBlockIdAndParamAndFromEpisode(String blockId, String param, String fromEpisode);

    long countByStatus(String status);
}
