package com.aiops.api.domain.agent;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;

import java.time.OffsetDateTime;

/**
 * V85 (2026-07-11) — 背景 Agent Task（build / skill_run）。
 *
 * 執行本體住 sidecar（asyncio task + 記憶體事件緩衝）；此表提供
 * (a) 跨 sidecar 重啟的狀態可見性、(b) terminal_events（done 卡＋圖卡
 * payload 的 SSE 事件 JSON array）供「離線期間完成」的工作在客戶端回放。
 */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "agent_tasks",
		indexes = @Index(name = "idx_agent_tasks_session", columnList = "chat_session_id, created_at"))
public class AgentTaskEntity {

	@Id
	@Column(name = "id", length = 64)
	private String id;

	@Column(name = "kind", nullable = false, length = 32)
	private String kind;

	@Column(name = "chat_session_id", nullable = false, length = 64)
	private String chatSessionId;

	@Column(name = "user_id")
	private Long userId;

	/** running | finished | failed | interrupted */
	@Column(name = "status", nullable = false, length = 24)
	private String status;

	@Column(name = "goal", columnDefinition = "text")
	private String goal;

	@CreationTimestamp
	@Column(name = "created_at", nullable = false, columnDefinition = "timestamp with time zone")
	private OffsetDateTime createdAt;

	@Column(name = "finished_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime finishedAt;

	@Column(name = "terminal_events", columnDefinition = "text")
	private String terminalEvents;
}
