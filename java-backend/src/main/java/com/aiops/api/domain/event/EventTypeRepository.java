package com.aiops.api.domain.event;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface EventTypeRepository extends JpaRepository<EventTypeEntity, Long> {
	Optional<EventTypeEntity> findByName(String name);
}
