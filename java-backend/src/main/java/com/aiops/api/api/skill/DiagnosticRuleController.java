package com.aiops.api.api.skill;

import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.skill.SkillDefinitionEntity;
import com.aiops.api.domain.skill.SkillDefinitionRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * Diagnostic rules = skills with {@code source='rule'} (historical naming).
 * Phase 2 cut: expose the list read surface; mutations remain on
 * SkillDefinitionController until Phase 8 retires the old engine.
 */
@RestController
@RequestMapping("/api/v1/diagnostic-rules")
@PreAuthorize(Authorities.ANY_ROLE)
public class DiagnosticRuleController {

	private final SkillDefinitionRepository repository;

	public DiagnosticRuleController(SkillDefinitionRepository repository) {
		this.repository = repository;
	}

	@GetMapping
	public ApiResponse<List<SkillDefinitionEntity>> list() {
		return ApiResponse.ok(repository.findBySource("rule"));
	}

	@GetMapping("/{id}")
	public ApiResponse<SkillDefinitionEntity> get(@PathVariable Long id) {
		return ApiResponse.ok(repository.findById(id)
				.orElseThrow(() -> new com.aiops.api.common.ApiException(
						org.springframework.http.HttpStatus.NOT_FOUND,
						"not_found",
						"diagnostic rule " + id + " not found")));
	}
}
