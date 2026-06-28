package com.aiops.api.api.internal;

import com.aiops.api.api.skill.SkillRunnerService;
import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.auth.Role;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.skill.SkillDefinitionEntity;
import com.aiops.api.domain.skill.SkillDefinitionRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Skill lookup for LangGraph tool_dispatcher inside the sidecar. */
@RestController
@RequestMapping("/internal/skills")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalSkillController {

	private final SkillDefinitionRepository repository;
	private final SkillRunnerService runnerService;
	private final com.aiops.api.api.skillv2.SkillV2RunnerService v2Runner;

	public InternalSkillController(SkillDefinitionRepository repository,
	                               SkillRunnerService runnerService,
	                               com.aiops.api.api.skillv2.SkillV2RunnerService v2Runner) {
		this.repository = repository;
		this.runnerService = runnerService;
		this.v2Runner = v2Runner;
	}

	/**
	 * Run a skills_v2 skill by id (cron / event scheduler path). Synchronous —
	 * executes the bound pipeline, evaluates the verdict, writes skill_run +
	 * (for patrol) an alarm. Body: {triggered_by?, trigger_payload?}.
	 */
	@PostMapping("/v2/{id}/run-system")
	public ApiResponse<Map<String, Object>> runV2FromSystem(
			@PathVariable Long id,
			@RequestBody(required = false) Map<String, Object> body) {
		Map<String, Object> b = body != null ? body : Map.of();
		@SuppressWarnings("unchecked")
		Map<String, Object> payload = b.get("trigger_payload") instanceof Map<?, ?> p
				? (Map<String, Object>) p : Map.of();
		String triggeredBy = b.get("triggered_by") instanceof String s && !s.isBlank()
				? s : "system";
		return ApiResponse.ok(v2Runner.runSystem(id, triggeredBy, payload));
	}

	@GetMapping
	public ApiResponse<List<Dto>> list(@RequestParam(required = false) String source) {
		var all = (source != null && !source.isBlank())
				? repository.findBySource(source) : repository.findAll();
		return ApiResponse.ok(all.stream().map(Dto::of).toList());
	}

	@GetMapping("/{id}")
	public ApiResponse<Dto> get(@PathVariable Long id) {
		return ApiResponse.ok(Dto.of(repository.findById(id)
				.orElseThrow(() -> ApiException.notFound("skill"))));
	}

	/**
	 * v6.1 (2026-05-20): system-fire endpoint for java-scheduler. Triggers a
	 * skill end-to-end with triggered_by tag (defaults "system" if not given).
	 * Fire-and-forget — returns immediately with 202-shaped ack while the
	 * runner executes asynchronously on the elastic scheduler.
	 *
	 * <p>Body: {"trigger_payload": {...}, "triggered_by": "system_schedule"}
	 */
	@PostMapping("/by-slug/{slug}/run-system")
	public ApiResponse<Map<String, Object>> runFromSystem(
			@PathVariable String slug,
			@RequestBody(required = false) Map<String, Object> body
	) {
		Map<String, Object> b = body != null ? body : Map.of();
		@SuppressWarnings("unchecked")
		Map<String, Object> payload = b.get("trigger_payload") instanceof Map<?, ?> p
				? (Map<String, Object>) p : Map.of();
		String triggeredBy = b.get("triggered_by") instanceof String s && !s.isBlank()
				? s : "system";

		// Synthetic system principal — userId=0 surfaces in audit; IT_ADMIN
		// role satisfies any downstream @PreAuthorize on the sidecar path.
		AuthPrincipal systemCaller = new AuthPrincipal(0L, "system", Set.of(Role.IT_ADMIN));

		// Fire-and-forget: subscribe so doOnSubscribe runs (creates SkillRunEntity
		// + kicks off runWithSink on elastic scheduler), discard event stream.
		runnerService.run(slug, payload, false, systemCaller, triggeredBy).subscribe();

		Map<String, Object> resp = new HashMap<>();
		resp.put("ok", true);
		resp.put("slug", slug);
		resp.put("triggered_by", triggeredBy);
		resp.put("status", "dispatched");
		return ApiResponse.ok(resp);
	}

	public record Dto(Long id, String name, String description, String triggerMode, String stepsMapping,
	                  String inputSchema, String outputSchema, String pipelineConfig,
	                  String source, String bindingType, Boolean isActive) {
		static Dto of(SkillDefinitionEntity e) {
			return new Dto(e.getId(), e.getName(), e.getDescription(), e.getTriggerMode(),
					e.getStepsMapping(), e.getInputSchema(), e.getOutputSchema(),
					e.getPipelineConfig(), e.getSource(), e.getBindingType(), e.getIsActive());
		}
	}
}
