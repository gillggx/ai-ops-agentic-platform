package com.aiops.api.domain.mcp;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface McpCapabilitySettingsRepository
        extends JpaRepository<McpCapabilitySettingsEntity, Long> {

    Optional<McpCapabilitySettingsEntity> findByCapabilityKey(String capabilityKey);
}
