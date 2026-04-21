package com.aiops.api.domain.event;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface GeneratedEventRepository extends JpaRepository<GeneratedEventEntity, Long> {
	List<GeneratedEventEntity> findByEventTypeId(Long eventTypeId);
	List<GeneratedEventEntity> findByStatus(String status);
}
