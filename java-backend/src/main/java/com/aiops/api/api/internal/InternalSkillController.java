package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.skill.SkillDefinitionEntity;
import com.aiops.api.domain.skill.SkillDefinitionRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/** Skill lookup for LangGraph tool_dispatcher inside the sidecar. */
@RestController
@RequestMapping("/internal/skills")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalSkillController {

	private final SkillDefinitionRepository repository;

	public InternalSkillController(SkillDefinitionRepository repository) {
		this.repository = repository;
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
