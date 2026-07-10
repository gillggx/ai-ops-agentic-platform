package com.aiops.api.api.agentskill;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.agentskill.AgentSkillEntity;
import com.aiops.api.domain.agentskill.AgentSkillRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;

/**
 * 標準 Skill CRUD (V82, 2026-07-10). The manuals are DATA — editable in the
 * admin GUI, versionless single source the Coordinator + external cowork both
 * read. Reads: any role. Writes: IT_ADMIN.
 */
@RestController
@RequestMapping("/api/v1/agent-skills")
public class AgentSkillController {

	private final AgentSkillRepository repository;

	public AgentSkillController(AgentSkillRepository repository) {
		this.repository = repository;
	}

	@GetMapping
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<AgentSkillEntity>> list() {
		return ApiResponse.ok(repository.findAllByOrderByNameAsc());
	}

	@GetMapping("/{name}")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<AgentSkillEntity> get(@PathVariable String name) {
		return ApiResponse.ok(repository.findByName(name)
				.orElseThrow(() -> ApiException.notFound("agent skill")));
	}

	@PostMapping
	@PreAuthorize(Authorities.ADMIN)
	@Transactional
	public ApiResponse<AgentSkillEntity> create(@RequestBody Map<String, Object> body,
	                                            @AuthenticationPrincipal AuthPrincipal caller) {
		String name = str(body.get("name"));
		if (name == null || name.isBlank()) throw ApiException.badRequest("name required");
		if (repository.findByName(name).isPresent()) throw ApiException.conflict("name already exists");
		AgentSkillEntity e = new AgentSkillEntity();
		e.setName(name.trim());
		apply(e, body, caller);
		return ApiResponse.ok(repository.save(e));
	}

	@PutMapping("/{name}")
	@PreAuthorize(Authorities.ADMIN)
	@Transactional
	public ApiResponse<AgentSkillEntity> update(@PathVariable String name,
	                                            @RequestBody Map<String, Object> body,
	                                            @AuthenticationPrincipal AuthPrincipal caller) {
		AgentSkillEntity e = repository.findByName(name)
				.orElseThrow(() -> ApiException.notFound("agent skill"));
		apply(e, body, caller);
		return ApiResponse.ok(repository.save(e));
	}

	@DeleteMapping("/{name}")
	@PreAuthorize(Authorities.ADMIN)
	@Transactional
	public ApiResponse<Map<String, Object>> delete(@PathVariable String name) {
		AgentSkillEntity e = repository.findByName(name)
				.orElseThrow(() -> ApiException.notFound("agent skill"));
		repository.delete(e);
		return ApiResponse.ok(Map.of("deleted", name));
	}

	private void apply(AgentSkillEntity e, Map<String, Object> body, AuthPrincipal caller) {
		if (body.containsKey("when_to_use")) {
			String w = str(body.get("when_to_use"));
			if (w == null || w.isBlank()) throw ApiException.badRequest("when_to_use required");
			e.setWhenToUse(w.trim());
		}
		if (body.containsKey("body")) {
			String b = str(body.get("body"));
			if (b == null || b.isBlank()) throw ApiException.badRequest("body required");
			e.setBody(b);
		}
		if (body.containsKey("enabled")) e.setEnabled(Boolean.TRUE.equals(body.get("enabled"))
				|| "true".equalsIgnoreCase(String.valueOf(body.get("enabled"))));
		e.setUpdatedBy(caller != null ? caller.username() : null);
		e.setUpdatedAt(OffsetDateTime.now(ZoneOffset.UTC));
	}

	private static String str(Object o) { return o == null ? null : String.valueOf(o); }
}
