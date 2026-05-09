package com.aiops.api.domain.alarm;

import com.aiops.api.domain.common.CreatedAtOnly;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "alarms",
		indexes = {
				@Index(name = "ix_alarms_skill_id", columnList = "skill_id"),
				@Index(name = "ix_alarms_trigger_event", columnList = "trigger_event"),
				@Index(name = "ix_alarms_equipment_id", columnList = "equipment_id"),
				@Index(name = "ix_alarms_lot_id", columnList = "lot_id"),
				@Index(name = "ix_alarms_execution_log_id", columnList = "execution_log_id"),
				@Index(name = "ix_alarms_diagnostic_log_id", columnList = "diagnostic_log_id")
		})
public class AlarmEntity extends CreatedAtOnly {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	/** Nullable: pipeline-based auto-patrols write alarms with skill_id=null
	 *  (no SkillDefinition row tied to them). DB schema has been nullable
	 *  since the pipeline-builder split; this field was incorrectly marked
	 *  nullable=false in JPA before. */
	@Column(name = "skill_id")
	private Long skillId;

	@Column(name = "trigger_event", nullable = false, length = 100)
	private String triggerEvent = "";

	@Column(name = "equipment_id", nullable = false, length = 100)
	private String equipmentId = "";

	@Column(name = "lot_id", nullable = false, length = 100)
	private String lotId = "";

	@Column(name = "step", length = 50)
	private String step;

	@Column(name = "event_time", columnDefinition = "timestamp with time zone")
	private OffsetDateTime eventTime;

	/** LOW | MEDIUM | HIGH | CRITICAL */
	@Column(name = "severity", nullable = false, length = 20)
	private String severity = "MEDIUM";

	@Column(name = "title", nullable = false, length = 300)
	private String title = "";

	@Column(name = "summary", columnDefinition = "text")
	private String summary;

	/** active | acknowledged | resolved */
	@Column(name = "status", nullable = false, length = 20)
	private String status = "active";

	@Column(name = "acknowledged_by", length = 100)
	private String acknowledgedBy;

	@Column(name = "acknowledged_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime acknowledgedAt;

	@Column(name = "resolved_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime resolvedAt;

	@Column(name = "execution_log_id")
	private Long executionLogId;

	@Column(name = "diagnostic_log_id")
	private Long diagnosticLogId;

	// ── Phase 12: structured ack / disposition ──────────────────────────
	// Differs from acknowledgedBy/acknowledgedAt above — those are loose
	// string fields predating real auth. The Phase 12 columns FK back to
	// users(id) so audit queries can join role/email/etc.

	@Column(name = "acked_by")
	private Long ackedBy;

	@Column(name = "acked_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime ackedAt;

	/** release | hold | scrap | rerun  (NULL = not yet disposed) */
	@Column(name = "disposition", length = 20)
	private String disposition;

	@Column(name = "disposition_reason", columnDefinition = "text")
	private String dispositionReason;

	@Column(name = "disposed_by")
	private Long disposedBy;

	@Column(name = "disposed_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime disposedAt;
}
