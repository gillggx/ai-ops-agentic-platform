package com.aiops.api.domain.user;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface RoleChangeLogRepository extends JpaRepository<RoleChangeLogEntity, Long> {
	List<RoleChangeLogEntity> findTop50ByOrderByChangedAtDesc();
	List<RoleChangeLogEntity> findByTargetUserIdOrderByChangedAtDesc(Long targetUserId);
}
