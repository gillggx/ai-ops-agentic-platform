package com.aiops.api.domain.skill;

import com.aiops.api.domain.common.Auditable;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "skill_definitions",
		indexes = {
				@Index(name = "ix_skill_definitions_name", columnList = "name", unique = true),
				@Index(name = "ix_skill_definitions_trigger_event_id", columnList = "trigger_event_id"),
				@Index(name = "ix_skill_definitions_trigger_patrol_id", columnList = "trigger_patrol_id")
		})
public class SkillDefinitionEntity extends Auditable {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "name", nullable = false, length = 200, unique = true)
	private String name;

	@Column(name = "description", nullable = false, columnDefinition = "text")
	private String description = "";

	@Column(name = "trigger_event_id")
	private Long triggerEventId;

	/** schedule | event | both */
	@Column(name = "trigger_mode", nullable = false, length = 20)
	private String triggerMode = "both";

	/** JSON text: [{step_id, nl_segment, python_code}] */
	@Column(name = "steps_mapping", nullable = false, columnDefinition = "text")
	private String stepsMapping = "[]";

	@Column(name = "input_schema", columnDefinition = "text")
	private String inputSchema = "[]";

	@Column(name = "output_schema", columnDefinition = "text")
	private String outputSchema = "[]";

	@Column(name = "pipeline_config", columnDefinition = "text")
	private String pipelineConfig;

	/** legacy | rule | auto_patrol | skill */
	@Column(name = "source", nullable = false, length = 20)
	private String source = "legacy";

	/** none | event | alarm */
	@Column(name = "binding_type", nullable = false, length = 20)
	private String bindingType = "none";

	@Column(name = "auto_check_description", nullable = false, columnDefinition = "text")
	private String autoCheckDescription = "";

	/** private | public */
	@Column(name = "visibility", nullable = false, length = 10)
	private String visibility = "private";

	@Column(name = "trigger_patrol_id")
	private Long triggerPatrolId;

	@Column(name = "created_by")
	private Long createdBy;

	@Column(name = "is_active", nullable = false)
	private Boolean isActive = Boolean.TRUE;
}
