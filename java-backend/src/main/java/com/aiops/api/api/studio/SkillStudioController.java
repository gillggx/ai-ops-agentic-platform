package com.aiops.api.api.studio;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 3-stage Skill Studio API surface.
 *
 * <p>Surfaces the new Skill Studio UI (画面 A) and Checklist Editor (画面 B)
 * without disturbing the existing {@code /api/v1/skill-documents/**}
 * routes (which the legacy Skill Library, Playbook, and dry-run page all
 * use). The Studio reads and writes {@link com.aiops.api.domain.skill.SkillStageEntity}
 * rows; on the wire each stage is a {@code StageDto}.
 *
 * <p>Endpoints:
 * <ul>
 *   <li>{@code GET    /api/v1/skill-studio/{slug}/stages} — return all three
 *       stages (auto-creates empty rows if missing so the UI never has to
 *       handle "no detect row yet"). Idempotent.</li>
 *   <li>{@code PUT    /api/v1/skill-studio/{slug}/stages/{kind}} — save
 *       prose / pipeline_id / trigger_config edits (draft only).</li>
 *   <li>{@code POST   /api/v1/skill-studio/{slug}/stages/{kind}/compile} —
 *       run AI compile of prose → rules. Phase 2 mock: returns canned
 *       rules per kind. Phase 5 wires real LLM (per
 *       feedback_cost_control_llm: Haiku via OpenRouter).</li>
 *   <li>{@code POST   /api/v1/skill-studio/{slug}/stages/{kind}/activate} —
 *       flips status draft → stable, freezes compiled_rules, stamps
 *       activated_at / activated_by.</li>
 * </ul>
 */
@RestController
@RequestMapping("/api/v1/skill-studio")
public class SkillStudioController {

	private final SkillStudioService service;

	public SkillStudioController(SkillStudioService service) {
		this.service = service;
	}

	@GetMapping("/{slug}/stages")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<SkillStudioService.StageDto>> listStages(@PathVariable String slug) {
		return ApiResponse.ok(service.listStages(slug));
	}

	@PutMapping("/{slug}/stages/{kind}")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<SkillStudioService.StageDto> saveStage(@PathVariable String slug,
	                                                          @PathVariable String kind,
	                                                          @RequestBody Map<String, Object> body) {
		return ApiResponse.ok(service.saveStage(slug, kind, body));
	}

	@PostMapping("/{slug}/stages/{kind}/compile")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<SkillStudioService.CompileResult> compileStage(@PathVariable String slug,
	                                                                   @PathVariable String kind,
	                                                                   @RequestBody Map<String, Object> body) {
		String prose = body == null ? "" : String.valueOf(body.getOrDefault("prose", ""));
		return ApiResponse.ok(service.compileStage(slug, kind, prose));
	}

	@PostMapping("/{slug}/stages/{kind}/activate")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<SkillStudioService.StageDto> activateStage(@PathVariable String slug,
	                                                              @PathVariable String kind,
	                                                              @AuthenticationPrincipal AuthPrincipal caller) {
		return ApiResponse.ok(service.activateStage(slug, kind, caller));
	}
}
