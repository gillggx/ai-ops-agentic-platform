package com.aiops.api.domain.pipeline;

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
@Table(name = "pb_pipeline_runs",
		indexes = {
				@Index(name = "ix_pb_pipeline_runs_pipeline_id", columnList = "pipeline_id"),
				@Index(name = "ix_pb_pipeline_runs_status", columnList = "status")
		})
public class PipelineRunEntity {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	/** Nullable for ad-hoc (un-saved) runs. */
	@Column(name = "pipeline_id")
	private Long pipelineId;

	@Column(name = "pipeline_version", nullable = false, length = 32)
	private String pipelineVersion = "adhoc";

	/** user | agent | schedule | event */
	@Column(name = "triggered_by", nullable = false, length = 32)
	private String triggeredBy = "user";

	/** running | success | failed | validation_error */
	@Column(name = "status", nullable = false, length = 32)
	private String status = "running";

	/** JSON text: `{node_id: {status, rows, duration_ms, error}}`. */
	@Column(name = "node_results", columnDefinition = "text")
	private String nodeResults;

	@Column(name = "error_message", columnDefinition = "text")
	private String errorMessage;

	@CreationTimestamp
	@Column(name = "started_at", nullable = false, columnDefinition = "timestamp with time zone")
	private OffsetDateTime startedAt;

	@Column(name = "finished_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime finishedAt;
}
