package com.aiops.api.domain.skill;

import com.aiops.api.domain.common.CreatedAtOnly;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "feedback_logs",
		indexes = {
				@Index(name = "ix_feedback_logs_target_type", columnList = "target_type"),
				@Index(name = "ix_feedback_logs_target_id", columnList = "target_id")
		})
public class FeedbackLogEntity extends CreatedAtOnly {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	/** mcp | skill */
	@Column(name = "target_type", nullable = false, length = 10)
	private String targetType;

	@Column(name = "target_id", nullable = false)
	private Long targetId;

	@Column(name = "user_feedback", nullable = false, columnDefinition = "text")
	private String userFeedback = "";

	@Column(name = "previous_result_summary", columnDefinition = "text")
	private String previousResultSummary;

	@Column(name = "llm_reflection", columnDefinition = "text")
	private String llmReflection;

	@Column(name = "revised_script", columnDefinition = "text")
	private String revisedScript;

	@Column(name = "rerun_success", nullable = false)
	private Boolean rerunSuccess = Boolean.FALSE;
}
