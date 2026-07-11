package com.aiops.api.api.agent;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.agent.AgentSessionEntity;
import com.aiops.api.domain.agent.AgentSessionRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/agent")
@PreAuthorize(Authorities.ANY_ROLE)
public class AgentSessionController {

	private final AgentSessionRepository repository;

	public AgentSessionController(AgentSessionRepository repository) {
		this.repository = repository;
	}

	@GetMapping("/sessions")
	public ApiResponse<List<Map<String, Object>>> list(@AuthenticationPrincipal AuthPrincipal caller,
	                                                    @RequestParam(defaultValue = "30") int limit) {
		Long uid = caller != null ? caller.userId() : null;
		int safe = Math.min(Math.max(limit, 1), 200);
		// ChatOps sidebar (2026-07-10): titled conversations only, newest first
		// (legacy null-title/null-updated_at rows used to bury every real one).
		var pageable = org.springframework.data.domain.PageRequest.of(0, safe);
		List<AgentSessionEntity> rows = (uid == null || uid == 0L)
				? repository.findTitled(pageable)
				: repository.findTitledByUser(uid, pageable);
		List<Map<String, Object>> out = rows.stream().map(s -> {
			Map<String, Object> m = new java.util.HashMap<>();
			m.put("session_id", s.getSessionId());
			m.put("user_id", s.getUserId());
			m.put("title", s.getTitle());
			m.put("created_at", s.getCreatedAt());
			m.put("updated_at", s.getUpdatedAt() != null ? s.getUpdatedAt() : s.getCreatedAt());
			m.put("has_pipeline", s.getLastPipelineJson() != null);
			m.put("cumulative_tokens", s.getCumulativeTokens());
			return m;
		}).toList();
		return ApiResponse.ok(out);
	}

	@GetMapping("/session/{sessionId}")
	public ApiResponse<AgentSessionEntity> getOne(@PathVariable String sessionId) {
		return ApiResponse.ok(repository.findById(sessionId)
				.orElseThrow(() -> ApiException.notFound("agent session")));
	}

	/** V85 (2026-07-11) — 跨裝置 rich history（完整訊息串含圖卡，opaque JSON）。 */
	@GetMapping("/session/{sessionId}/rich-history")
	public ApiResponse<Map<String, Object>> getRichHistory(@PathVariable String sessionId) {
		AgentSessionEntity e = repository.findById(sessionId)
				.orElseThrow(() -> ApiException.notFound("agent session"));
		return ApiResponse.ok(Map.of("rich_history",
				e.getRichHistory() == null ? "" : e.getRichHistory()));
	}

	@PutMapping("/session/{sessionId}/rich-history")
	public ApiResponse<Void> putRichHistory(@PathVariable String sessionId,
	                                        @RequestBody Map<String, Object> body) {
		AgentSessionEntity e = repository.findById(sessionId)
				.orElseThrow(() -> ApiException.notFound("agent session"));
		Object blob = body.get("rich_history");
		if (blob instanceof String s) {
			if (s.length() > 2_000_000) {
				throw ApiException.badRequest("rich_history too large (>2MB)");
			}
			e.setRichHistory(s);
			repository.save(e);
		}
		return ApiResponse.ok(null);
	}
}
