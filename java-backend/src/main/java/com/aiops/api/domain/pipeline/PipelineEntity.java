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
@Table(name = "pb_pipelines",
		indexes = @Index(name = "ix_pb_pipelines_name", columnList = "name"))
public class PipelineEntity extends Auditable {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "name", nullable = false, length = 128)
	private String name;

	@Column(name = "description", nullable = false, columnDefinition = "text")
	private String description = "";

	/** draft | validating | locked | active | archived */
	@Column(name = "status", nullable = false, length = 20)
	private String status = "draft";

	/** auto_patrol | diagnostic (Phase 5-UX-3b: nullable, deprecated name) */
	@Column(name = "pipeline_kind", length = 20)
	private String pipelineKind;

	@Column(name = "version", nullable = false, length = 32)
	private String version = "1.0.0";

	/** DAG structure as JSON text. */
	@Column(name = "pipeline_json", nullable = false, columnDefinition = "text")
	private String pipelineJson = "{}";

	/** Invocation telemetry as JSON text. */
	@Column(name = "usage_stats", nullable = false, columnDefinition = "text")
	private String usageStats = "{\"invoke_count\":0,\"last_invoked_at\":null,\"last_triggered_at\":null}";

	@Column(name = "auto_doc", columnDefinition = "text")
	private String autoDoc;

	@Column(name = "locked_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime lockedAt;

	@Column(name = "locked_by", columnDefinition = "text")
	private String lockedBy;

	@Column(name = "published_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime publishedAt;

	@Column(name = "archived_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime archivedAt;

	@Column(name = "created_by")
	private Long createdBy;

	@Column(name = "approved_by")
	private Long approvedBy;

	@Column(name = "approved_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime approvedAt;

	/** Self-reference for pipeline fork / version chain. */
	@Column(name = "parent_id")
	private Long parentId;
}
