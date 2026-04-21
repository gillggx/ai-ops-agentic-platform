package com.aiops.api.domain.user;

import com.aiops.api.domain.common.Auditable;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "users",
		indexes = {
				@Index(name = "ix_users_username", columnList = "username", unique = true),
				@Index(name = "ix_users_email", columnList = "email", unique = true)
		})
public class UserEntity extends Auditable {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "username", nullable = false, length = 150, unique = true)
	private String username;

	@Column(name = "email", nullable = false, length = 255, unique = true)
	private String email;

	@Column(name = "hashed_password", nullable = false, length = 255)
	private String hashedPassword;

	@Column(name = "is_active", nullable = false)
	private Boolean isActive = Boolean.TRUE;

	@Column(name = "is_superuser", nullable = false)
	private Boolean isSuperuser = Boolean.FALSE;

	/** JSON-serialised list of role strings (legacy TEXT storage). */
	@Column(name = "roles", nullable = false, columnDefinition = "text")
	private String roles = "[]";
}
