package com.aiops.api.domain.handoff;

import org.springframework.data.jpa.repository.JpaRepository;

public interface UiHandoffRepository extends JpaRepository<UiHandoffEntity, String> {
}
