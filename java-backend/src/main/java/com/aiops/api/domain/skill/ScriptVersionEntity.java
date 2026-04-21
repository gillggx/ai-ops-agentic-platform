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
@Table(name = "script_versions",
		indexes = {
				@Index(name = "ix_script_versions_skill_id", columnList = "skill_id"),
				@Index(name = "ix_script_versions_status", columnList = "status")
		})
public class ScriptVersionEntity {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "skill_id", nullable = false)
	private Long skillId;

	@Column(name = "version", nullable = false)
	private Integer version = 1;

	/** draft | approved | active | deprecated */
	@Column(name = "status", nullable = false, length = 20)
	private String status = "draft";

	@Column(name = "code", nullable = false, columnDefinition = "text")
	private String code;

	@Column(name = "change_note", columnDefinition = "text")
	private String changeNote;

	@Column(name = "reviewed_by", length = 100)
	private String reviewedBy;

	@Column(name = "approved_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime approvedAt;

	@CreationTimestamp
	@Column(name = "generated_at", nullable = false, columnDefinition = "timestamp with time zone")
	private OffsetDateTime generatedAt;
}
