package com.aiops.api.domain.supervisor;

import org.springframework.data.jpa.repository.JpaRepository;

import java.time.OffsetDateTime;
import java.util.List;

public interface SupervisorActionRepository extends JpaRepository<SupervisorActionEntity, Long> {

    List<SupervisorActionEntity> findTop200ByStatusOrderByIdDesc(String status);

    List<SupervisorActionEntity> findTop200ByOrderByIdDesc();

    long countByStatus(String status);

    /** Dedup guard: one live proposal per (type, targets). */
    boolean existsByActionTypeAndTargetIdsAndStatus(String actionType, String targetIds, String status);

    /** W3 forensics: open queue — proposed and not superseded by a newer
     *  proposal (supersede detection input for the CLI). */
    List<SupervisorActionEntity> findByStatusAndSupersededByIsNullOrderByIdDesc(String status);

    /** W3 verify queue: landed before {@code cutoff} and never verified.
     *  {@code landedAt < cutoff} implies landed_at IS NOT NULL (SQL NULL
     *  comparison), oldest landing first so the CLI works FIFO. */
    List<SupervisorActionEntity> findByVerifyAtIsNullAndLandedAtBeforeOrderByLandedAtAsc(
            OffsetDateTime cutoff);
}
