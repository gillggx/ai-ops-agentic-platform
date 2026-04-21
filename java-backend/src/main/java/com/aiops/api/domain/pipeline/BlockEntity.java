package com.aiops.api.domain.pipeline;

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
@Table(name = "pb_blocks",
		indexes = @Index(name = "ix_pb_blocks_name", columnList = "name"),
		uniqueConstraints = @UniqueConstraint(name = "uq_pb_blocks_name_version", columnNames = {"name", "version"}))
public class BlockEntity extends Auditable {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "name", nullable = false, length = 128)
	private String name;

	@Column(name = "category", nullable = false, length = 32)
	private String category;

	@Column(name = "version", nullable = false, length = 32)
	private String version = "1.0.0";

	/** draft | active | deprecated (per seed) */
	@Column(name = "status", nullable = false, length = 16)
	private String status = "draft";

	@Column(name = "description", nullable = false, columnDefinition = "text")
	private String description = "";

	@Column(name = "input_schema", nullable = false, columnDefinition = "text")
	private String inputSchema = "[]";

	@Column(name = "output_schema", nullable = false, columnDefinition = "text")
	private String outputSchema = "[]";

	@Column(name = "param_schema", nullable = false, columnDefinition = "text")
	private String paramSchema = "{}";

	@Column(name = "implementation", nullable = false, columnDefinition = "text")
	private String implementation = "{}";

	/** JSON: usage examples (LLM Q&A corpus). */
	@Column(name = "examples", nullable = false, columnDefinition = "text")
	private String examples = "[]";

	/** JSON: actual runtime output columns. */
	@Column(name = "output_columns_hint", nullable = false, columnDefinition = "text")
	private String outputColumnsHint = "[]";

	@Column(name = "is_custom", nullable = false)
	private Boolean isCustom = Boolean.FALSE;

	@Column(name = "created_by")
	private Long createdBy;

	@Column(name = "approved_by")
	private Long approvedBy;

	@Column(name = "approved_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime approvedAt;

	@Column(name = "review_note", columnDefinition = "text")
	private String reviewNote;
}
