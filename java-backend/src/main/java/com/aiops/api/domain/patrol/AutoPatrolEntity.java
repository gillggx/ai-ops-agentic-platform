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
				@Index(name = "ix_auto_patrols_event_type_id", columnList = "event_type_id"),
				@Index(name = "ix_auto_patrols_skill_doc_id", columnList = "skill_doc_id")
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

	/** Phase 11 — set when this row was materialized from a skill_documents
	 *  row. Multiple auto_patrol rows may share the same skill_doc_id (one
	 *  per skill step). Used for de-publish cleanup. */
	@Column(name = "skill_doc_id")
	private Long skillDocId;

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

	// ── Phase 9 (2026-05-08): Personal rule fields ──────────────────────────
	// `kind=shared_alarm` (default for existing rows) keeps the legacy
	// alarm-generating behaviour. Other kinds (personal_briefing /
	// weekly_report / saved_query / watch_rule) signal NotificationDispatch
	// to push to inbox instead of generating alarms.

	/** shared_alarm | personal_briefing | weekly_report | saved_query | watch_rule */
	@Column(name = "kind", nullable = false, length = 40)
	private String kind = "shared_alarm";

	/** JSON array — Phase 9-A only honours [{"type":"in_app"}]. */
	@Column(name = "notification_channels", columnDefinition = "text")
	private String notificationChannels;

	/** "上週 OOC top-5: {top_tools}" — placeholders resolved against pipeline output. */
	@Column(name = "notification_template", columnDefinition = "text")
	private String notificationTemplate;

	@Column(name = "last_dispatched_at")
	private OffsetDateTime lastDispatchedAt;
}
