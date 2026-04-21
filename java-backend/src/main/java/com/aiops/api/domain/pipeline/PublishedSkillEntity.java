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
@Table(name = "pb_published_skills",
		indexes = {
				@Index(name = "ix_pb_published_skills_pipeline_id", columnList = "pipeline_id"),
				@Index(name = "ix_pb_published_skills_slug", columnList = "slug", unique = true)
		},
		uniqueConstraints = @UniqueConstraint(name = "uq_pbps_pipeline_version",
				columnNames = {"pipeline_id", "pipeline_version"}))
public class PublishedSkillEntity {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "pipeline_id", nullable = false)
	private Long pipelineId;

	@Column(name = "pipeline_version", nullable = false, length = 32)
	private String pipelineVersion;

	@Column(name = "slug", nullable = false, length = 80, unique = true)
	private String slug;

	@Column(name = "name", nullable = false, length = 128)
	private String name;

	@Column(name = "use_case", nullable = false, columnDefinition = "text")
	private String useCase = "";

	/** JSON list. */
	@Column(name = "when_to_use", nullable = false, columnDefinition = "text")
	private String whenToUse = "[]";

	@Column(name = "inputs_schema", nullable = false, columnDefinition = "text")
	private String inputsSchema = "[]";

	@Column(name = "outputs_schema", nullable = false, columnDefinition = "text")
	private String outputsSchema = "{}";

	@Column(name = "example_invocation", columnDefinition = "text")
	private String exampleInvocation;

	@Column(name = "tags", nullable = false, columnDefinition = "text")
	private String tags = "[]";

	/** active | retired */
	@Column(name = "status", nullable = false, length = 16)
	private String status = "active";

	@Column(name = "published_by", columnDefinition = "text")
	private String publishedBy;

	@CreationTimestamp
	@Column(name = "published_at", nullable = false, columnDefinition = "timestamp with time zone")
	private OffsetDateTime publishedAt;

	@Column(name = "retired_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime retiredAt;
}
