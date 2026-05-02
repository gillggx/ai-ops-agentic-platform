package com.aiops.api.domain.user;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

/** Audit trail for /admin/users role upgrades + demotes. */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "role_change_logs",
		indexes = {
				@Index(name = "ix_rcl_target", columnList = "target_user_id"),
				@Index(name = "ix_rcl_changed_at", columnList = "changed_at")
		})
public class RoleChangeLogEntity {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "target_user_id", nullable = false)
	private Long targetUserId;

	@Column(name = "actor_user_id")
	private Long actorUserId;

	@Column(name = "old_roles", nullable = false, columnDefinition = "text")
	private String oldRoles;

	@Column(name = "new_roles", nullable = false, columnDefinition = "text")
	private String newRoles;

	@Column(name = "reason", columnDefinition = "text")
	private String reason;

	@Column(name = "changed_at", nullable = false)
	private OffsetDateTime changedAt = OffsetDateTime.now();
}
