package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.agent.AgentTaskEntity;
import com.aiops.api.domain.agent.AgentTaskRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

/**
 * V85 (2026-07-11) — sidecar 背景 Agent Task 的持久層。
 * sidecar 在 task 建立 / 完成時 upsert；list 供任何裝置 reattach 時查
 * 「這個對話有沒有進行中 / 剛完成的工作」。
 */
@RestController
@RequestMapping("/internal/agent-tasks")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalAgentTaskController {

	private final AgentTaskRepository repository;

	public InternalAgentTaskController(AgentTaskRepository repository) {
		this.repository = repository;
	}

	@GetMapping
	public ApiResponse<List<Dto>> list(@RequestParam("chat_session_id") String chatSessionId) {
		return ApiResponse.ok(repository
				.findTop10ByChatSessionIdOrderByCreatedAtDesc(chatSessionId)
				.stream().map(Dto::of).toList());
	}

	/** ChatOps rail 最近運作 (2026-07-13)：本人跨對話近期工作（點了跳回該對話）。 */
	@GetMapping("/recent")
	public ApiResponse<List<Dto>> recent(@RequestParam("user_id") Long userId) {
		return ApiResponse.ok(repository
				.findTop10ByUserIdOrderByCreatedAtDesc(userId)
				.stream().map(Dto::of).toList());
	}

	@GetMapping("/{id}")
	public ApiResponse<Dto> get(@PathVariable String id) {
		return repository.findById(id)
				.map(e -> ApiResponse.ok(Dto.of(e)))
				.orElseGet(() -> ApiResponse.ok(null));
	}

	@PutMapping("/{id}")
	@Transactional
	public ApiResponse<Dto> upsert(@PathVariable String id, @RequestBody Map<String, Object> body) {
		AgentTaskEntity e = repository.findById(id).orElseGet(AgentTaskEntity::new);
		if (e.getId() == null) e.setId(id);
		if (body.get("kind") instanceof String v) e.setKind(v);
		if (body.get("chat_session_id") instanceof String v) e.setChatSessionId(v);
		if (body.get("user_id") instanceof Number v) e.setUserId(v.longValue());
		if (body.get("status") instanceof String v) {
			e.setStatus(v);
			if (!"running".equals(v) && e.getFinishedAt() == null) {
				e.setFinishedAt(OffsetDateTime.now());
			}
		}
		if (body.get("goal") instanceof String v) e.setGoal(v);
		if (body.get("terminal_events") instanceof String v) e.setTerminalEvents(v);
		return ApiResponse.ok(Dto.of(repository.save(e)));
	}

	public record Dto(String id, String kind, String chat_session_id, Long user_id,
	                  String status, String goal, OffsetDateTime created_at,
	                  OffsetDateTime finished_at, String terminal_events) {
		static Dto of(AgentTaskEntity e) {
			return new Dto(e.getId(), e.getKind(), e.getChatSessionId(), e.getUserId(),
					e.getStatus(), e.getGoal(), e.getCreatedAt(), e.getFinishedAt(),
					e.getTerminalEvents());
		}
	}
}
