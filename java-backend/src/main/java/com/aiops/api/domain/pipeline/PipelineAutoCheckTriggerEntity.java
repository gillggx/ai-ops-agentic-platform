package com.aiops.api.domain.pipeline;

import com.aiops.api.domain.common.CreatedAtOnly;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "pipeline_auto_check_triggers",
		indexes = {
				@Index(name = "ix_pipeline_auto_check_triggers_pipeline_id", columnList = "pipeline_id"),
				@Index(name = "ix_pipeline_auto_check_triggers_event_type", columnList = "event_type"),
				@Index(name = "ix_auto_check_skill_doc", columnList = "skill_doc_id")
		},
		uniqueConstraints = @UniqueConstraint(name = "uq_pacheck_pipeline_event",
				columnNames = {"pipeline_id", "event_type"}))
public class PipelineAutoCheckTriggerEntity extends CreatedAtOnly {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "pipeline_id", nullable = false)
	private Long pipelineId;

	@Column(name = "event_type", nullable = false, length = 128)
	private String eventType;

	/** Phase D — JSON object {alarm_field: value | [value,...]}. NULL means
	 *  no filter (every alarm with matching event_type fires the pipeline).
	 *  Evaluated by EventDispatchService.matchFilter. */
	@Column(name = "match_filter", columnDefinition = "text")
	private String matchFilter;

	/** Phase 11 — set when this row was materialized from a skill_documents
	 *  trigger_config. Multiple rows may share skill_doc_id (one per step). */
	@Column(name = "skill_doc_id")
	private Long skillDocId;
}
