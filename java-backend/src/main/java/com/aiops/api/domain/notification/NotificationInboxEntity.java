package com.aiops.api.domain.notification;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

/**
 * Phase 9 — per-user notification inbox written by NotificationDispatch
 * when a personal-rule auto_patrols row fires. The bell-icon widget reads
 * this; alarm-center reads alarm_definitions instead.
 *
 * Payload is opaque JSON ({@code title}, {@code body}, {@code rule_id},
 * {@code run_id}, {@code chart_id?}). Channel-specific extensions go
 * inside payload — no schema migration needed.
 */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "notification_inbox",
		indexes = {
				@Index(name = "ix_notification_inbox_user_recent", columnList = "user_id, created_at"),
		})
public class NotificationInboxEntity {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "user_id", nullable = false)
	private Long userId;

	@Column(name = "rule_id")
	private Long ruleId;

	@Column(name = "payload", nullable = false, columnDefinition = "text")
	private String payload;

	@Column(name = "read_at")
	private OffsetDateTime readAt;

	@Column(name = "created_at", nullable = false)
	private OffsetDateTime createdAt = OffsetDateTime.now();
}
