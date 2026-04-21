package com.aiops.api.domain.system;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.OffsetDateTime;

@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "system_parameters",
		indexes = @Index(name = "ix_system_parameters_key", columnList = "key", unique = true))
public class SystemParameterEntity {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "key", nullable = false, length = 100, unique = true)
	private String key;

	@Column(name = "value", columnDefinition = "text")
	private String value;

	@Column(name = "description", length = 500)
	private String description;

	@UpdateTimestamp
	@Column(name = "updated_at", nullable = false, columnDefinition = "timestamp with time zone")
	private OffsetDateTime updatedAt;
}
