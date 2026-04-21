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
@Table(name = "pb_canvas_operations",
		indexes = @Index(name = "ix_pb_canvas_operations_pipeline_id", columnList = "pipeline_id"))
public class CanvasOperationEntity extends CreatedAtOnly {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "pipeline_id")
	private Long pipelineId;

	/** user | agent */
	@Column(name = "actor", nullable = false, length = 32)
	private String actor = "user";

	@Column(name = "operation", nullable = false, length = 32)
	private String operation;

	@Column(name = "payload", nullable = false, columnDefinition = "text")
	private String payload = "{}";

	@Column(name = "reasoning", columnDefinition = "text")
	private String reasoning;
}
