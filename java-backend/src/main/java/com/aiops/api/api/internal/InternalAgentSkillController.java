package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.agentskill.AgentSkillEntity;
import com.aiops.api.domain.agentskill.AgentSkillRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/** 標準 Skill for the Coordinator (V82): /index rides in the system prompt
 *  (name + when_to_use only); /{name} is the full manual the load_skill tool
 *  fetches on demand. */
@RestController
@RequestMapping("/internal/agent-skills")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalAgentSkillController {

	private final AgentSkillRepository repository;

	public InternalAgentSkillController(AgentSkillRepository repository) {
		this.repository = repository;
	}

	@GetMapping("/index")
	public ApiResponse<List<Map<String, Object>>> index() {
		return ApiResponse.ok(repository.findByEnabledTrueOrderByNameAsc().stream()
				.map(s -> Map.<String, Object>of(
						"name", s.getName(),
						"when_to_use", s.getWhenToUse()))
				.toList());
	}

	@GetMapping("/{name}")
	public ApiResponse<Map<String, Object>> get(@PathVariable String name) {
		AgentSkillEntity e = repository.findByName(name)
				.filter(s -> Boolean.TRUE.equals(s.getEnabled()))
				.orElseThrow(() -> ApiException.notFound("agent skill"));
		return ApiResponse.ok(Map.of("name", e.getName(),
				"when_to_use", e.getWhenToUse(), "body", e.getBody()));
	}
}
