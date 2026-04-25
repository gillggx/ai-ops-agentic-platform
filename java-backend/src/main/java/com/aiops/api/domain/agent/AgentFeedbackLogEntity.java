package com.aiops.api.domain.agent;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;

import java.time.OffsetDateTime;

/**
 * User feedback on an agent answer (👍 / 👎 + optional reason).
 *
 * <p>Recorded per ({@code session_id}, {@code message_idx}, {@code user_id})
 * tuple — re-rating overwrites the prior row (see
 * {@link AgentFeedbackLogRepository#findBySessionIdAndMessageIdxAndUserId}).
 */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "agent_feedback_log",
		uniqueConstraints = @UniqueConstraint(
				name = "ux_agent_feedback_log_session_message_user",
				columnNames = {"session_id", "message_idx", "user_id"}),
		indexes = {
				@Index(name = "ix_agent_feedback_log_session", columnList = "session_id"),
				@Index(name = "ix_agent_feedback_log_created_at", columnList = "created_at"),
		})
public class AgentFeedbackLogEntity {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "session_id", nullable = false, length = 100)
	private String sessionId;

	@Column(name = "user_id", nullable = false)
	private Long userId;

	@Column(name = "message_idx", nullable = false)
	private Integer messageIdx;

	/** 1 = 👍, -1 = 👎. */
	@Column(name = "rating", nullable = false)
	private Short rating;

	/** "data_wrong" | "logic_wrong" | "chart_unclear" — null on 👍. */
	@Column(name = "reason", length = 40)
	private String reason;

	@Column(name = "free_text", length = 500)
	private String freeText;

	@Column(name = "contract_summary", columnDefinition = "text")
	private String contractSummary;

	@Column(name = "tools_used", columnDefinition = "text")
	private String toolsUsed;

	@CreationTimestamp
	@Column(name = "created_at", nullable = false, columnDefinition = "timestamp with time zone")
	private OffsetDateTime createdAt;
}
