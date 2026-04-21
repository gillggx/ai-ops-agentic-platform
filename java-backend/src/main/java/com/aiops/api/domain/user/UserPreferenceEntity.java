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
@Table(name = "user_preferences",
		indexes = @Index(name = "ix_user_preferences_user_id", columnList = "user_id", unique = true))
public class UserPreferenceEntity extends Auditable {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "user_id", nullable = false, unique = true)
	private Long userId;

	@Column(name = "preferences", columnDefinition = "text")
	private String preferences;

	@Column(name = "soul_override", columnDefinition = "text")
	private String soulOverride;
}
