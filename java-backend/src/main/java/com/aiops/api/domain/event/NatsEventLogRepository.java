package com.aiops.api.domain.event;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface NatsEventLogRepository extends JpaRepository<NatsEventLogEntity, Long> {
}
