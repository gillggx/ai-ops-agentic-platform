package com.aiops.api.domain.notification;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface NotificationInboxRepository extends JpaRepository<NotificationInboxEntity, Long> {

	/** Bell-icon hot path — unread for current user, newest first. */
	@Query("SELECT n FROM NotificationInboxEntity n " +
			"WHERE n.userId = :userId AND n.readAt IS NULL " +
			"ORDER BY n.createdAt DESC")
	List<NotificationInboxEntity> findUnreadByUser(@Param("userId") Long userId);

	/** Dropdown view — recent N for user (read or unread). */
	@Query("SELECT n FROM NotificationInboxEntity n " +
			"WHERE n.userId = :userId " +
			"ORDER BY n.createdAt DESC")
	List<NotificationInboxEntity> findRecentByUser(@Param("userId") Long userId,
	                                               org.springframework.data.domain.Pageable page);

	long countByUserIdAndReadAtIsNull(Long userId);
}
