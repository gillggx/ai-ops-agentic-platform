package com.aiops.api.api.skill;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.skill.SkillDefinitionEntity;
import com.aiops.api.domain.skill.SkillDefinitionRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/** Skills created by the current caller (per-user namespace). */
@RestController
@RequestMapping("/api/v1/my-skills")
@PreAuthorize(Authorities.ANY_ROLE)
public class MySkillsController {

	private final SkillDefinitionRepository repository;

	public MySkillsController(SkillDefinitionRepository repository) {
		this.repository = repository;
	}

	@GetMapping
	public ApiResponse<List<SkillDefinitionEntity>> list(@AuthenticationPrincipal AuthPrincipal caller) {
		if (caller == null || caller.userId() == null || caller.userId() == 0L) {
			// shared-secret caller — return all, mirroring Python's behaviour
			return ApiResponse.ok(repository.findAll());
		}
		Long uid = caller.userId();
		return ApiResponse.ok(repository.findAll().stream()
				.filter(s -> uid.equals(s.getCreatedBy()))
				.toList());
	}
}
