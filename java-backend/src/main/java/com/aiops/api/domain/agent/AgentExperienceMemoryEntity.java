package com.aiops.api.domain.agent;

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
@Table(name = "agent_experience_memory",
		indexes = {
				@Index(name = "ix_agent_experience_memory_user_id", columnList = "user_id"),
				@Index(name = "ix_agent_experience_memory_status", columnList = "status")
		})
public class AgentExperienceMemoryEntity extends Auditable {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "user_id", nullable = false)
	private Long userId;

	@Column(name = "intent_summary", nullable = false, length = 500)
	private String intentSummary;

	@Column(name = "abstract_action", nullable = false, columnDefinition = "text")
	private String abstractAction;

	/**
	 * pgvector(1024) — bge-m3 1024-dim embedding. Stored as raw String in Phase 1;
	 * Phase 3 will introduce a dedicated converter + similarity search.
	 */
	@Column(name = "embedding", columnDefinition = "vector(1024)")
	private String embedding;

	@Column(name = "confidence_score", nullable = false)
	private Integer confidenceScore = 5;

	@Column(name = "use_count", nullable = false)
	private Integer useCount = 0;

	@Column(name = "success_count", nullable = false)
	private Integer successCount = 0;

	@Column(name = "fail_count", nullable = false)
	private Integer failCount = 0;

	/** ACTIVE | STALE | HUMAN_REJECTED */
	@Column(name = "status", nullable = false, length = 20)
	private String status = "ACTIVE";

	/** auto | user_explicit | system */
	@Column(name = "source", nullable = false, length = 50)
	private String source = "auto";

	@Column(name = "source_session_id", length = 100)
	private String sourceSessionId;

	@Column(name = "last_used_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime lastUsedAt;
}
