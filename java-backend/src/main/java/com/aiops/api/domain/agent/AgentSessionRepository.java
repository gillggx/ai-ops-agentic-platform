package com.aiops.api.domain.agent;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface AgentSessionRepository extends JpaRepository<AgentSessionEntity, String> {
	List<AgentSessionEntity> findByUserIdOrderByUpdatedAtDesc(Long userId);
	List<AgentSessionEntity> findByUserIdOrderByUpdatedAtDesc(Long userId, Pageable pageable);

	/** ChatOps sidebar (2026-07-10): only titled conversations, newest first.
	 *  COALESCE because legacy rows (pre-title era) have NULL updated_at and
	 *  Postgres puts NULLs FIRST on DESC — they buried every real session. */
	@org.springframework.data.jpa.repository.Query(
			"SELECT s FROM AgentSessionEntity s WHERE s.userId = :userId AND s.title IS NOT NULL " +
			"ORDER BY COALESCE(s.updatedAt, s.createdAt) DESC")
	List<AgentSessionEntity> findTitledByUser(
			@org.springframework.data.repository.query.Param("userId") Long userId, Pageable pageable);

	@org.springframework.data.jpa.repository.Query(
			"SELECT s FROM AgentSessionEntity s WHERE s.title IS NOT NULL " +
			"ORDER BY COALESCE(s.updatedAt, s.createdAt) DESC")
	List<AgentSessionEntity> findTitled(Pageable pageable);
}
