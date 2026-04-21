package com.aiops.api.domain.skill;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;

import java.time.OffsetDateTime;

@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "execution_logs",
		indexes = {
				@Index(name = "ix_execution_logs_skill_id", columnList = "skill_id"),
				@Index(name = "ix_execution_logs_auto_patrol_id", columnList = "auto_patrol_id"),
				@Index(name = "ix_execution_logs_cron_job_id", columnList = "cron_job_id"),
				@Index(name = "ix_execution_logs_status", columnList = "status")
		})
public class ExecutionLogEntity {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "skill_id", nullable = false)
	private Long skillId;

	@Column(name = "auto_patrol_id")
	private Long autoPatrolId;

	@Column(name = "script_version_id")
	private Long scriptVersionId;

	@Column(name = "cron_job_id")
	private Long cronJobId;

	/** cron | event | manual | agent | auto_patrol */
	@Column(name = "triggered_by", nullable = false, length = 80)
	private String triggeredBy = "manual";

	/** JSON EventContext snapshot. */
	@Column(name = "event_context", columnDefinition = "text")
	private String eventContext;

	/** success | error | timeout */
	@Column(name = "status", nullable = false, length = 20)
	private String status = "success";

	@Column(name = "llm_readable_data", columnDefinition = "text")
	private String llmReadableData;

	@Column(name = "action_dispatched", length = 50)
	private String actionDispatched;

	@Column(name = "error_message", columnDefinition = "text")
	private String errorMessage;

	@CreationTimestamp
	@Column(name = "started_at", nullable = false, columnDefinition = "timestamp with time zone")
	private OffsetDateTime startedAt;

	@Column(name = "finished_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime finishedAt;

	@Column(name = "duration_ms")
	private Long durationMs;
}
