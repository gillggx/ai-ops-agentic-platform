package com.aiops.api.domain.supervisor;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface SupervisorActionRepository extends JpaRepository<SupervisorActionEntity, Long> {

    List<SupervisorActionEntity> findTop200ByStatusOrderByIdDesc(String status);

    List<SupervisorActionEntity> findTop200ByOrderByIdDesc();

    long countByStatus(String status);

    /** Dedup guard: one live proposal per (type, targets). */
    boolean existsByActionTypeAndTargetIdsAndStatus(String actionType, String targetIds, String status);
}
