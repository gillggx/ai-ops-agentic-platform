package com.aiops.api.domain.agent;

import com.aiops.api.domain.common.Auditable;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "agent_memories",
		indexes = {
				@Index(name = "ix_agent_memories_user_id", columnList = "user_id"),
				@Index(name = "ix_agent_memories_task_type", columnList = "task_type"),
				@Index(name = "ix_agent_memories_data_subject", columnList = "data_subject")
		})
public class AgentMemoryEntity extends Auditable {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "user_id", nullable = false)
	private Long userId;

	@Column(name = "content", nullable = false, columnDefinition = "text")
	private String content;

	/**
	 * JSON float array (dev Text storage). Prod may migrate to pgvector later;
	 * keep as TEXT for now to match Python SQLAlchemy's Text column.
	 */
	@Column(name = "embedding", columnDefinition = "text")
	private String embedding;

	/** diagnosis | agent_request | manual */
	@Column(name = "source", length = 50)
	private String source;

	@Column(name = "ref_id", length = 100)
	private String refId;

	@Column(name = "task_type", length = 100)
	private String taskType;

	@Column(name = "data_subject", length = 200)
	private String dataSubject;

	@Column(name = "tool_name", length = 100)
	private String toolName;
}
