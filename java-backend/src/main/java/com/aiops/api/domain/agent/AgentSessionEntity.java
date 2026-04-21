package com.aiops.api.domain.agent;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.OffsetDateTime;

@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "agent_sessions",
		indexes = @Index(name = "ix_agent_sessions_user_id", columnList = "user_id"))
public class AgentSessionEntity {

	@Id
	@Column(name = "session_id", length = 36)
	private String sessionId;

	@Column(name = "user_id", nullable = false)
	private Long userId;

	/** JSON text: [{role, content}]. */
	@Column(name = "messages", nullable = false, columnDefinition = "text")
	private String messages = "[]";

	@CreationTimestamp
	@Column(name = "created_at", nullable = false, columnDefinition = "timestamp with time zone")
	private OffsetDateTime createdAt;

	@Column(name = "expires_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime expiresAt;

	@Column(name = "cumulative_tokens")
	private Integer cumulativeTokens = 0;

	@Column(name = "workspace_state", columnDefinition = "text")
	private String workspaceState;

	@Column(name = "last_pipeline_json", columnDefinition = "text")
	private String lastPipelineJson;

	@Column(name = "last_pipeline_run_id")
	private Long lastPipelineRunId;

	@Column(name = "title", length = 200)
	private String title;

	@UpdateTimestamp
	@Column(name = "updated_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime updatedAt;
}
