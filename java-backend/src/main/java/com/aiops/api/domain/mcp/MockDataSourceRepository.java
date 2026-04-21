package com.aiops.api.domain.mcp;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface MockDataSourceRepository extends JpaRepository<MockDataSourceEntity, Long> {
	Optional<MockDataSourceEntity> findByName(String name);
}
