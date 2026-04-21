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
@Table(name = "items",
		indexes = {
				@Index(name = "ix_items_title", columnList = "title"),
				@Index(name = "ix_items_owner_id", columnList = "owner_id")
		})
public class ItemEntity extends Auditable {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "title", nullable = false, length = 255)
	private String title;

	@Column(name = "description", columnDefinition = "text")
	private String description;

	@Column(name = "is_active", nullable = false)
	private Boolean isActive = Boolean.TRUE;

	@Column(name = "owner_id", nullable = false)
	private Long ownerId;
}
