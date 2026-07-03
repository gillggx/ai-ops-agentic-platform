package com.aiops.api.domain.agentknowledge;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface BlockDocMemoRepository extends JpaRepository<BlockDocMemoEntity, Long> {

    /** Dedup: one memo per (block, param, episode). */
    boolean existsByBlockIdAndParamAndFromEpisode(String blockId, String param, String fromEpisode);

    long countByStatus(String status);

    /** Newest-first, capped — for the /agent-knowledge Builder-memory view. */
    List<BlockDocMemoEntity> findTop200ByOrderByIdDesc();

    /** Curation input (V72): pending memos awaiting Supervisor review. */
    List<BlockDocMemoEntity> findTop100ByStatusOrderByIdDesc(String status);

    /** Monitor (V73): blocks whose pending doc memos reached the threshold. */
    @org.springframework.data.jpa.repository.Query(value = """
            SELECT block_id, count(*) AS n FROM block_doc_memos
            WHERE status = 'pending'
            GROUP BY block_id HAVING count(*) >= :minCount
            ORDER BY n DESC
            """, nativeQuery = true)
    List<Object[]> pendingCountsByBlock(@org.springframework.data.repository.query.Param("minCount") long minCount);
}
