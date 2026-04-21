package com.aiops.api.domain.user;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface UserPreferenceRepository extends JpaRepository<UserPreferenceEntity, Long> {
	Optional<UserPreferenceEntity> findByUserId(Long userId);
}
