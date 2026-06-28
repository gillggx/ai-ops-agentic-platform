package com.aiops.api.api.skillv2;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * Skills v2 API surface — CRUD + compile + save-automation.
 *
 * <p>Lives at {@code /api/v2/skills/**} so the legacy {@code /api/v1/skill-documents/**}
 * routes can be retired in a follow-up without code churn during the
 * transition. Currently nothing depends on /api/v1/skill-documents from
 * the v2 UI; once /patrol-activity is migrated to query skills_v2 + the
 * scheduler is rewired, the v1 surface can drop.
 */
@RestController
@RequestMapping("/api/v2/skills")
public class SkillV2Controller {

	private final SkillV2Service service;

	public SkillV2Controller(SkillV2Service service) {
		this.service = service;
	}

	@GetMapping
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<SkillV2Service.SkillDto>> list() {
		return ApiResponse.ok(service.list());
	}

	/** Create a new skill. Body: {slug, name, sub?, nl?, in_type?, out_type?}. */
	@PostMapping
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<SkillV2Service.SkillDto> create(@RequestBody Map<String, Object> body) {
		return ApiResponse.ok(service.create(body));
	}

	/**
	 * Cowork one-shot: create pipeline + skill + bind in one transaction.
	 * Lands as status='draft' (NOT active). Body:
	 * {slug, name, sub?, nl?, pipeline_json, pipeline_kind?}.
	 */
	@PostMapping("/with-pipeline")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<SkillV2Service.SkillFullDto> createWithPipeline(
			@RequestBody Map<String, Object> body,
			@AuthenticationPrincipal AuthPrincipal caller) {
		Long uid = caller != null ? caller.userId() : null;
		return ApiResponse.ok(service.createWithPipeline(body, uid));
	}

	/** Human pressed 啟用 — draft → active. */
	@PostMapping("/{slug}/activate")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<SkillV2Service.SkillDto> activate(@PathVariable String slug) {
		return ApiResponse.ok(service.activate(slug));
	}

	/** Stop scheduling — active → draft (config preserved). */
	@PostMapping("/{slug}/deactivate")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<SkillV2Service.SkillDto> deactivate(@PathVariable String slug) {
		return ApiResponse.ok(service.deactivate(slug));
	}

	@GetMapping("/{slug}")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<SkillV2Service.SkillDto> get(@PathVariable String slug) {
		return ApiResponse.ok(service.get(slug));
	}

	/**
	 * NL → pipeline compile. Phase 1 (this commit) returns the existing
	 * compiled pipeline_nodes from the row (mock). Phase 6+ swaps in an
	 * LLM call. Compile is read-only — caller must {@link #saveSkill} to
	 * persist edits.
	 */
	@PostMapping("/{slug}/compile")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<SkillV2Service.CompileResult> compile(@PathVariable String slug,
	                                                          @RequestBody Map<String, Object> body) {
		String nl = body == null ? "" : String.valueOf(body.getOrDefault("nl", ""));
		return ApiResponse.ok(service.compile(slug, nl));
	}

	/** Save NL + (optionally) compiled pipeline_nodes back to the row. */
	@PutMapping("/{slug}")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<SkillV2Service.SkillDto> saveSkill(@PathVariable String slug,
	                                                       @RequestBody Map<String, Object> body) {
		return ApiResponse.ok(service.saveSkill(slug, body));
	}

	@DeleteMapping("/{slug}")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<Void> deleteSkill(@PathVariable String slug) {
		service.deleteSkill(slug);
		return ApiResponse.ok(null);
	}

	/** Cowork MCP one-shot: skill + its bound pipeline_json in one round-trip. */
	@GetMapping("/{slug}/full")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<SkillV2Service.SkillFullDto> getSkillFull(@PathVariable String slug) {
		return ApiResponse.ok(service.getFull(slug));
	}

	/** Cowork pre-flight: can this skill be promoted to {role}?
	 *  Returns {ok: bool, reason?: str}. */
	@GetMapping("/{slug}/role-readiness")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<SkillV2Service.RoleReadinessDto> roleReadiness(
			@PathVariable String slug,
			@RequestParam String role) {
		return ApiResponse.ok(service.checkRoleReadiness(slug, role));
	}

	/** Apply automation (role + trigger + gate + outcome). NULL trigger → tool. */
	@PostMapping("/{slug}/automation")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<SkillV2Service.SkillDto> saveAutomation(@PathVariable String slug,
	                                                            @RequestBody Map<String, Object> body) {
		return ApiResponse.ok(service.saveAutomation(slug, body));
	}

	/** Strip automation — flip role back to tool, clear trigger/gate/outcome. */
	@DeleteMapping("/{slug}/automation")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<SkillV2Service.SkillDto> removeAutomation(@PathVariable String slug) {
		return ApiResponse.ok(service.removeAutomation(slug));
	}

	/**
	 * Bind a pb_pipeline to this skill. Loads the pipeline_json, converts
	 * its nodes into the PipelineNode[] representation the Editor renders,
	 * derives has_alarm from any block_step_check node, and persists both
	 * pipeline_id + pipeline_nodes on skills_v2.
	 *
	 * <p>Called from Pipeline Builder's auto-bind hook when the embed
	 * context is {@code skill-v2}, and from the cowork MCP tool
	 * {@code bind_skill_pipeline}.
	 */
	@PostMapping("/{slug}/bind-pipeline")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<SkillV2Service.SkillDto> bindPipeline(@PathVariable String slug,
	                                                          @RequestBody Map<String, Object> body) {
		Number pid = (Number) body.get("pipeline_id");
		if (pid == null) {
			return ApiResponse.ok(service.get(slug));  // no-op
		}
		return ApiResponse.ok(service.bindPipeline(slug, pid.longValue()));
	}

	/** Convenience: list peer "alarming" patrols an event-driven skill can subscribe to. */
	@GetMapping("/alarm-sources")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<SkillV2Service.AlarmSourceDto>> listAlarmSources(@RequestParam(required = false) String excludeSlug) {
		return ApiResponse.ok(service.listAlarmSources(excludeSlug));
	}
}
