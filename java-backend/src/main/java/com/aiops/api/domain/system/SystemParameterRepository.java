package com.aiops.api.domain.system;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface SystemParameterRepository extends JpaRepository<SystemParameterEntity, Long> {
	Optional<SystemParameterEntity> findByKey(String key);
}
