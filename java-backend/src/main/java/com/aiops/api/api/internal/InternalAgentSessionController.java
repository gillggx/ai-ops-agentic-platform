package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.agent.AgentSessionEntity;
import com.aiops.api.domain.agent.AgentSessionRepository;
import jakarta.validation.constraints.NotNull;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;

/**
 * LangGraph checkpointer backing store. The sidecar pushes session message
 * lists + workspace state; on every turn it reads the latest snapshot back.
 */
@RestController
@RequestMapping("/internal/agent-sessions")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalAgentSessionController {

	private final AgentSessionRepository repository;

	public InternalAgentSessionController(AgentSessionRepository repository) {
		this.repository = repository;
	}

	@GetMapping("/{sessionId}")
	public ApiResponse<Dto> get(@PathVariable String sessionId) {
		AgentSessionEntity e = repository.findById(sessionId)
				.orElseThrow(() -> ApiException.notFound("agent session"));
		return ApiResponse.ok(Dto.of(e));
	}

	@PutMapping("/{sessionId}")
	@Transactional
	public ApiResponse<Dto> upsert(@PathVariable String sessionId,
	                               @Validated @RequestBody UpsertRequest req) {
		AgentSessionEntity e = repository.findById(sessionId).orElseGet(AgentSessionEntity::new);
		if (e.getSessionId() == null) e.setSessionId(sessionId);
		e.setUserId(req.userId());
		if (req.messages() != null) e.setMessages(req.messages());
		if (req.workspaceState() != null) e.setWorkspaceState(req.workspaceState());
		if (req.lastPipelineJson() != null) e.setLastPipelineJson(req.lastPipelineJson());
		if (req.lastPipelineRunId() != null) e.setLastPipelineRunId(req.lastPipelineRunId());
		if (req.cumulativeTokens() != null) e.setCumulativeTokens(req.cumulativeTokens());
		if (req.title() != null) e.setTitle(req.title());
		if (req.expiresAt() != null) e.setExpiresAt(req.expiresAt());
		Dto out = Dto.of(repository.save(e));
		// V86 (2026-07-12) 對話保留政策：近期 >5 則 → 最舊打包（清 rich_history
		// 只留文字）；打包歷史 >10 則 → 最舊刪除。在對話成形（有 title）的
		// 寫入點強制，正在寫入的這筆是最新的，不會被打包到。
		if (e.getTitle() != null) {
			enforceRetention(req.userId());
		}
		return ApiResponse.ok(out);
	}

	private void enforceRetention(Long userId) {
		var active = repository.findActiveTitledByUserOldestFirst(userId);
		for (int i = 0; i < active.size() - 5; i++) {
			var s = active.get(i);
			s.setArchivedAt(OffsetDateTime.now());
			s.setRichHistory(null);
			repository.save(s);
		}
		var archived = repository.findByUserIdAndArchivedAtIsNotNullOrderByArchivedAtAsc(userId);
		for (int i = 0; i < archived.size() - 10; i++) {
			repository.delete(archived.get(i));
		}
	}

	// `messages` is intentionally not @NotBlank: partial upserts (e.g. just
	// stamping last_pipeline_json after a build) skip it and the controller
	// leaves the existing value alone. userId is still required so we can't
	// stamp on a brand-new session row anonymously.
	public record UpsertRequest(@NotNull Long userId, String messages,
	                            String workspaceState, String lastPipelineJson,
	                            Long lastPipelineRunId, Integer cumulativeTokens,
	                            String title, OffsetDateTime expiresAt) {}

	public record Dto(String sessionId, Long userId, String messages, String workspaceState,
	                  String lastPipelineJson, Long lastPipelineRunId, Integer cumulativeTokens,
	                  String title, OffsetDateTime createdAt, OffsetDateTime updatedAt,
	                  OffsetDateTime expiresAt) {
		static Dto of(AgentSessionEntity e) {
			return new Dto(e.getSessionId(), e.getUserId(), e.getMessages(), e.getWorkspaceState(),
					e.getLastPipelineJson(), e.getLastPipelineRunId(), e.getCumulativeTokens(),
					e.getTitle(), e.getCreatedAt(), e.getUpdatedAt(), e.getExpiresAt());
		}
	}
}
