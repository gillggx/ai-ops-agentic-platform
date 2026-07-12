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

	/** V86 (2026-07-12) 打包政策 — 近期（未打包）由舊到新，供超額打包。 */
	@org.springframework.data.jpa.repository.Query(
			"SELECT s FROM AgentSessionEntity s WHERE s.userId = :userId AND s.title IS NOT NULL " +
			"AND s.archivedAt IS NULL ORDER BY COALESCE(s.updatedAt, s.createdAt) ASC")
	List<AgentSessionEntity> findActiveTitledByUserOldestFirst(
			@org.springframework.data.repository.query.Param("userId") Long userId);

	/** V86 — 打包歷史由舊到新，供超過 10 則刪除。 */
	List<AgentSessionEntity> findByUserIdAndArchivedAtIsNotNullOrderByArchivedAtAsc(Long userId);
}
