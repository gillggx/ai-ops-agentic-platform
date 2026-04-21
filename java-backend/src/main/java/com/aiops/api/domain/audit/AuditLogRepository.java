package com.aiops.api.domain.audit;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.OffsetDateTime;

@Repository
public interface AuditLogRepository extends JpaRepository<AuditLogEntity, Long> {

	@Modifying
	@Query("DELETE FROM AuditLogEntity a WHERE a.createdAt < :cutoff")
	int deleteOlderThan(@Param("cutoff") OffsetDateTime cutoff);
}
