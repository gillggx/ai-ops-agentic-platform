package com.aiops.api.domain.alarm;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface AlarmRepository extends JpaRepository<AlarmEntity, Long> {
	List<AlarmEntity> findByStatusOrderByCreatedAtDesc(String status);
	List<AlarmEntity> findBySkillIdOrderByCreatedAtDesc(Long skillId);

	// Stats count — avoids loading 4k alarm rows into heap just to group by severity.
	@Query(value = "SELECT LOWER(COALESCE(severity, 'medium')) AS sev, COUNT(*) AS c "
			+ "FROM alarms WHERE (:status IS NULL OR status = :status) "
			+ "GROUP BY LOWER(COALESCE(severity, 'medium'))", nativeQuery = true)
	List<Object[]> countBySeverityGrouped(@Param("status") String status);
}
