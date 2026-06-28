package com.aiops.api.domain.skill;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.OffsetDateTime;

/**
 * V65 (2026-06-28) — one row per stage per skill in the 3-stage Skill
 * Studio. Stays side-by-side with {@link SkillDocumentEntity} so the
 * existing single-stage {@code steps[]} surface keeps working unchanged.
 *
 * <p>Lifecycle:
 * <ol>
 *   <li>A skill author writes {@code prose} for each stage in the new
 *       Skill Studio UI.</li>
 *   <li>"Re-compile" calls the LLM (Phase 5; mock stub in Phase 2) and
 *       writes {@code compiled_rules} as JSON.</li>
 *   <li>Activate flips {@code status} draft → stable, freezes
 *       {@code compiled_rules}, and stamps activated_at / activated_by.</li>
 *   <li>The scheduler reads {@code stable} stages and dispatches per
 *       stage trigger (DETECT cron / DIAGNOSE event / RECOVER pattern).</li>
 * </ol>
 *
 * <p>Stage independence is the whole point: previously the scheduler had to
 * conflate "what triggers this skill" with "what runs inside", because both
 * lived on {@code skill_documents}. Now {@code skill_stages} owns trigger +
 * compiled rules per stage; the scheduler dispatches each independently.
 */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "skill_stages",
		uniqueConstraints = @UniqueConstraint(name = "uq_skill_stages_doc_kind",
				columnNames = {"skill_doc_id", "kind"}),
		indexes = {
				@Index(name = "ix_skill_stages_skill_doc_id", columnList = "skill_doc_id"),
				@Index(name = "ix_skill_stages_pipeline_id",  columnList = "pipeline_id"),
				@Index(name = "ix_skill_stages_kind_status",  columnList = "kind, status"),
		})
public class SkillStageEntity {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "skill_doc_id", nullable = false)
	private Long skillDocId;

	/** detect | diagnose | recover */
	@Column(name = "kind", nullable = false, length = 20)
	private String kind;

	@Column(name = "trigger_config", nullable = false, columnDefinition = "text")
	private String triggerConfig = "{}";

	@Column(name = "prose", nullable = false, columnDefinition = "text")
	private String prose = "";

	@Column(name = "compiled_rules", nullable = false, columnDefinition = "text")
	private String compiledRules = "[]";

	/** DIAGNOSE only — which pb_pipeline implements this stage. */
	@Column(name = "pipeline_id")
	private Long pipelineId;

	/** draft | stable — only 'stable' is dispatched by the scheduler. */
	@Column(name = "status", nullable = false, length = 20)
	private String status = "draft";

	@Column(name = "version", nullable = false, length = 20)
	private String version = "0.1";

	@Column(name = "activated_at")
	private OffsetDateTime activatedAt;

	@Column(name = "activated_by")
	private Long activatedBy;

	@CreationTimestamp
	@Column(name = "created_at", nullable = false, updatable = false)
	private OffsetDateTime createdAt;

	@UpdateTimestamp
	@Column(name = "updated_at", nullable = false)
	private OffsetDateTime updatedAt;
}
