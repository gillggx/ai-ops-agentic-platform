package com.aiops.api.domain.skillv2;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.OffsetDateTime;

/**
 * V66 (2026-06-28) — Skills v2. Skill = 1 pipeline + optional automation.
 *
 * <p>Replaces the multi-step shape held by {@code skill_documents}:
 * <ul>
 *   <li>Skill identity + NL prose + 1 pipeline binding (no steps[] array)</li>
 *   <li>Automation is optional fields on the same row — trigger / gate /
 *       outcome. NULL automation → {@code role='tool'}.</li>
 *   <li>{@code role} (tool | patrol | datacheck) is derived from automation
 *       + has_alarm; persisted denormalised for fast filter on the Library
 *       page.</li>
 * </ul>
 *
 * <p>{@code pipeline_nodes} is the compiled-result JSON the Editor renders.
 * The connection to {@code pb_pipelines} via {@code pipeline_id} is the
 * real source of truth for execution; pipeline_nodes is a view cached
 * here so the Library + Editor don't need a JOIN.
 */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "skills_v2",
		indexes = {
				@Index(name = "ix_skills_v2_role",        columnList = "role"),
				@Index(name = "ix_skills_v2_pipeline_id", columnList = "pipeline_id"),
				@Index(name = "ix_skills_v2_status_role", columnList = "status, role"),
		})
public class SkillV2Entity {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "slug", nullable = false, unique = true)
	private String slug;

	@Column(name = "name", nullable = false)
	private String name;

	@Column(name = "sub", nullable = false, columnDefinition = "text")
	private String sub = "";

	@Column(name = "nl", nullable = false, columnDefinition = "text")
	private String nl = "";

	@Column(name = "pipeline_id")
	private Long pipelineId;

	/** JSON: list of {k, t, s, isVerdict?} — what the Editor's right column renders. */
	@Column(name = "pipeline_nodes", nullable = false, columnDefinition = "text")
	private String pipelineNodes = "[]";

	@Column(name = "has_alarm", nullable = false)
	private Boolean hasAlarm = Boolean.FALSE;

	@Column(name = "in_type", nullable = false)
	private String inType = "";

	@Column(name = "out_type", nullable = false)
	private String outType = "";

	/** tool | patrol | datacheck (derived; persisted for filter speed). */
	@Column(name = "role", nullable = false)
	private String role = "tool";

	/** JSON: {kind: schedule|event, schedule?, target?, source?}. NULL = tool. */
	@Column(name = "trigger_config", columnDefinition = "text")
	private String triggerConfig;

	@Column(name = "alarm_gate", columnDefinition = "text")
	private String alarmGate;

	@Column(name = "outcome", columnDefinition = "text")
	private String outcome;

	@Column(name = "status", nullable = false)
	private String status = "draft";

	@Column(name = "test_cases", nullable = false, columnDefinition = "text")
	private String testCases = "[]";

	@Column(name = "created_by")
	private Long createdBy;

	@CreationTimestamp
	@Column(name = "created_at", nullable = false, updatable = false)
	private OffsetDateTime createdAt;

	@UpdateTimestamp
	@Column(name = "updated_at", nullable = false)
	private OffsetDateTime updatedAt;
}
