package com.aiops.api.domain.event;

import com.aiops.api.domain.common.Auditable;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "event_types",
		indexes = @Index(name = "ix_event_types_name", columnList = "name", unique = true))
public class EventTypeEntity extends Auditable {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "name", nullable = false, length = 200, unique = true)
	private String name;

	@Column(name = "description", nullable = false, columnDefinition = "text")
	private String description = "";

	/** simulator | webhook | manual */
	@Column(name = "source", nullable = false, length = 50)
	private String source = "simulator";

	@Column(name = "is_active", nullable = false)
	private Boolean isActive = Boolean.TRUE;

	/** Legacy JSON text field */
	@Column(name = "attributes", nullable = false, columnDefinition = "text")
	private String attributes = "[]";

	/** Legacy JSON text field */
	@Column(name = "diagnosis_skill_ids", nullable = false, columnDefinition = "text")
	private String diagnosisSkillIds = "[]";
}
