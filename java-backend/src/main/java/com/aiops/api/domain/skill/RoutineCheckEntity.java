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
@Table(name = "routine_checks",
		indexes = {
				@Index(name = "ix_routine_checks_name", columnList = "name"),
				@Index(name = "ix_routine_checks_skill_id", columnList = "skill_id")
		})
public class RoutineCheckEntity extends Auditable {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "name", nullable = false, length = 200)
	private String name;

	@Column(name = "skill_id", nullable = false)
	private Long skillId;

	/** JSON text — NOTE: DB column is `preset_parameters` (legacy name). */
	@Column(name = "preset_parameters", nullable = false, columnDefinition = "text")
	private String skillInput = "{}";

	@Column(name = "trigger_event_id")
	private Long triggerEventId;

	@Column(name = "event_param_mappings", columnDefinition = "text")
	private String eventParamMappings;

	/** 30m | 1h | 4h | 8h | 12h | daily */
	@Column(name = "schedule_interval", nullable = false, length = 20)
	private String scheduleInterval = "1h";

	@Column(name = "is_active", nullable = false)
	private Boolean isActive = Boolean.TRUE;

	@Column(name = "last_run_at", columnDefinition = "text")
	private String lastRunAt;

	/** NORMAL | ABNORMAL | ERROR */
	@Column(name = "last_run_status", length = 20)
	private String lastRunStatus;

	@Column(name = "expire_at", columnDefinition = "text")
	private String expireAt;

	@Column(name = "schedule_time", length = 5)
	private String scheduleTime;
}
