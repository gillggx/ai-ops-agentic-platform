package com.aiops.api.domain.patrol;

import com.aiops.api.domain.common.Auditable;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "auto_patrols",
		indexes = {
				@Index(name = "ix_auto_patrols_skill_id", columnList = "skill_id"),
				@Index(name = "ix_auto_patrols_pipeline_id", columnList = "pipeline_id"),
				@Index(name = "ix_auto_patrols_event_type_id", columnList = "event_type_id")
		})
public class AutoPatrolEntity extends Auditable {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "name", nullable = false, length = 200)
	private String name;

	@Column(name = "description", nullable = false, columnDefinition = "text")
	private String description = "";

	/** Legacy link — skill_id now optional, pipeline_id is new path. */
	@Column(name = "skill_id")
	private Long skillId;

	@Column(name = "pipeline_id")
	private Long pipelineId;

	@Column(name = "input_binding", columnDefinition = "text")
	private String inputBinding;

	/** event | schedule | once */
	@Column(name = "trigger_mode", nullable = false, length = 20)
	private String triggerMode = "schedule";

	@Column(name = "event_type_id")
	private Long eventTypeId;

	@Column(name = "cron_expr", length = 100)
	private String cronExpr;

	/** For trigger_mode=once — one-shot DateTrigger fires at this UTC timestamp. */
	@Column(name = "scheduled_at")
	private OffsetDateTime scheduledAt;

	@Column(name = "auto_check_description", nullable = false, columnDefinition = "text")
	private String autoCheckDescription = "";

	/** recent_ooc | active_lots | tool_status */
	@Column(name = "data_context", nullable = false, length = 100)
	private String dataContext = "recent_ooc";

	/** JSON text — scope config. */
	@Column(name = "target_scope", nullable = false, columnDefinition = "text")
	private String targetScope = "{\"type\":\"event_driven\"}";

	@Column(name = "alarm_severity", length = 20)
	private String alarmSeverity;

	@Column(name = "alarm_title", length = 300)
	private String alarmTitle;

	@Column(name = "notify_config", columnDefinition = "text")
	private String notifyConfig;

	@Column(name = "is_active", nullable = false)
	private Boolean isActive = Boolean.TRUE;

	@Column(name = "created_by")
	private Long createdBy;
}
