package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.skill.SkillDefinitionEntity;
import com.aiops.api.domain.skill.SkillDefinitionRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/** Skill lookup for LangGraph tool_dispatcher inside the sidecar. */
@RestController
@RequestMapping("/internal/skills")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalSkillController {

	private final SkillDefinitionRepository repository;
	private final com.aiops.api.api.skillv2.SkillV2RunnerService v2Runner;

	public InternalSkillController(SkillDefinitionRepository repository,
	                               com.aiops.api.api.skillv2.SkillV2RunnerService v2Runner) {
		this.repository = repository;
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

	// Legacy by-slug/run-system (SkillRunnerService, skill_documents model)
	// removed in the 2026-06-29 sunset. The scheduler now fires v2 skills via
	// /internal/skills/v2/{id}/run-system above.

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
