package com.aiops.api.domain.pipeline;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface BlockRepository extends JpaRepository<BlockEntity, Long> {
	Optional<BlockEntity> findByNameAndVersion(String name, String version);
	List<BlockEntity> findByCategory(String category);
	List<BlockEntity> findByStatus(String status);
}
