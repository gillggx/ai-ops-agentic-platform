package com.aiops.api.domain.agent;

import com.aiops.api.domain.common.CreatedAtOnly;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "agent_drafts",
		indexes = @Index(name = "ix_agent_drafts_user_id", columnList = "user_id"))
public class AgentDraftEntity extends CreatedAtOnly {

	@Id
	@Column(name = "id", length = 36)
	private String id;

	/** mcp | skill | schedule | event */
	@Column(name = "draft_type", nullable = false, length = 20)
	private String draftType;

	/** JSON payload (shape varies by draft_type). */
	@Column(name = "payload", nullable = false, columnDefinition = "text")
	private String payload = "{}";

	@Column(name = "user_id", nullable = false)
	private Long userId;

	/** pending | published */
	@Column(name = "status", nullable = false, length = 10)
	private String status = "pending";
}
