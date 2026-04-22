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
		List<AgentSessionEntity> rows;
		if (uid == null || uid == 0L) {
			rows = repository.findAll();
		} else {
			rows = repository.findByUserIdOrderByUpdatedAtDesc(uid);
		}
		int safe = Math.min(Math.max(limit, 1), 200);
		List<Map<String, Object>> out = rows.stream().limit(safe).map(s -> {
			Map<String, Object> m = new java.util.HashMap<>();
			m.put("session_id", s.getSessionId());
			m.put("user_id", s.getUserId());
			m.put("title", s.getTitle());
			m.put("created_at", s.getCreatedAt());
			m.put("updated_at", s.getUpdatedAt());
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
}
