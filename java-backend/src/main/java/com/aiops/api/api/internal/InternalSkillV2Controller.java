package com.aiops.api.api.internal;

import com.aiops.api.api.skillv2.SkillV2Service;
import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/** Domain-Skill reads for the internal Coordinator (2026-07-10 — the
 *  domain-skill-management 標準 Skill's tools. These existed only on the
 *  external MCP server; the granted keys had no internal dispatch, so
 *  「有哪些 domain skills」一問就倒). Thin delegates to SkillV2Service. */
@RestController
@RequestMapping("/internal/skills-v2")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalSkillV2Controller {

	private final SkillV2Service service;

	public InternalSkillV2Controller(SkillV2Service service) {
		this.service = service;
	}

	@GetMapping
	public ApiResponse<List<SkillV2Service.SkillDto>> list() {
		return ApiResponse.ok(service.list());
	}

	@GetMapping("/alarm-sources")
	public ApiResponse<List<SkillV2Service.AlarmSourceDto>> alarmSources(
			@RequestParam(required = false) String excludeSlug) {
		return ApiResponse.ok(service.listAlarmSources(excludeSlug));
	}

	@GetMapping("/{slug}")
	public ApiResponse<SkillV2Service.SkillDto> get(@PathVariable String slug) {
		return ApiResponse.ok(service.get(slug));
	}

	@GetMapping("/{slug}/role-readiness")
	public ApiResponse<SkillV2Service.RoleReadinessDto> readiness(
			@PathVariable String slug, @RequestParam String role) {
		return ApiResponse.ok(service.checkRoleReadiness(slug, role));
	}
}
