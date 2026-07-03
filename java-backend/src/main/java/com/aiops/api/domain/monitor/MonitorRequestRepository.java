package com.aiops.api.domain.monitor;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface MonitorRequestRepository extends JpaRepository<MonitorRequestEntity, Long> {

    List<MonitorRequestEntity> findTop200ByStatusOrderByIdDesc(String status);

    List<MonitorRequestEntity> findTop200ByOrderByIdDesc();

    /** Dedup guard: one OPEN request per (kind, subject). */
    boolean existsByKindAndSubjectAndStatus(String kind, String subject, String status);

    long countByStatus(String status);
}
