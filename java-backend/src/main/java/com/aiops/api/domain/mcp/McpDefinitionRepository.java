package com.aiops.api.domain.mcp;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface McpDefinitionRepository extends JpaRepository<McpDefinitionEntity, Long> {
	Optional<McpDefinitionEntity> findByName(String name);
	List<McpDefinitionEntity> findByMcpType(String mcpType);
}
