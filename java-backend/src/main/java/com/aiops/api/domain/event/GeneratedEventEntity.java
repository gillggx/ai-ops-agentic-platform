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
@Table(name = "generated_events",
		indexes = {
				@Index(name = "ix_generated_events_event_type_id", columnList = "event_type_id"),
				@Index(name = "ix_generated_events_status", columnList = "status")
		})
public class GeneratedEventEntity extends Auditable {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "event_type_id", nullable = false)
	private Long eventTypeId;

	@Column(name = "source_skill_id", nullable = false)
	private Long sourceSkillId;

	@Column(name = "source_routine_check_id")
	private Long sourceRoutineCheckId;

	/** JSON text: parameters mapped from LLM. */
	@Column(name = "mapped_parameters", nullable = false, columnDefinition = "text")
	private String mappedParameters = "{}";

	@Column(name = "skill_conclusion", columnDefinition = "text")
	private String skillConclusion;

	/** pending | acknowledged | resolved */
	@Column(name = "status", nullable = false, length = 20)
	private String status = "pending";
}
