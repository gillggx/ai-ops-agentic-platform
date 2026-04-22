package com.aiops.api.api.pipeline;

import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.pipeline.BlockEntity;
import com.aiops.api.domain.pipeline.BlockRepository;
import com.aiops.api.domain.pipeline.PipelineAutoCheckTriggerRepository;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.pipeline.PublishedSkillEntity;
import com.aiops.api.domain.pipeline.PublishedSkillRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * Path-parity wrapper: Frontend proxies call {@code /api/v1/pipeline-builder/*}
 * which is how the old Python namespaced these endpoints. New native Java paths
 * are under {@code /api/v1/pipelines}, {@code /api/v1/published-skills} etc.
 * We keep both namespaces until Phase 8 retires the path aliases.
 */
@RestController
@RequestMapping("/api/v1/pipeline-builder")
@PreAuthorize(Authorities.ANY_ROLE)
public class PipelineBuilderController {

	private final PipelineRepository pipelineRepo;
	private final BlockRepository blockRepo;
	private final PublishedSkillRepository publishedSkillRepo;
	private final PipelineAutoCheckTriggerRepository autoCheckRepo;

	public PipelineBuilderController(PipelineRepository pipelineRepo,
	                                 BlockRepository blockRepo,
	                                 PublishedSkillRepository publishedSkillRepo,
	                                 PipelineAutoCheckTriggerRepository autoCheckRepo) {
		this.pipelineRepo = pipelineRepo;
		this.blockRepo = blockRepo;
		this.publishedSkillRepo = publishedSkillRepo;
		this.autoCheckRepo = autoCheckRepo;
	}

	@GetMapping("/pipelines")
	public List<PipelineEntity> listPipelines(@RequestParam(required = false) String status) {
		return (status != null && !status.isBlank())
				? pipelineRepo.findByStatus(status) : pipelineRepo.findAll();
	}

	@GetMapping("/pipelines/{id}")
	public PipelineEntity getPipeline(@PathVariable Long id) {
		return pipelineRepo.findById(id).orElseThrow(() -> ApiException.notFound("pipeline"));
	}

	@GetMapping("/blocks")
	public List<BlockEntity> listBlocks() {
		return blockRepo.findAll();
	}

	@GetMapping("/published-skills")
	public List<PublishedSkillEntity> listPublishedSkills(@RequestParam(required = false) String status) {
		return (status != null && !status.isBlank())
				? publishedSkillRepo.findByStatus(status) : publishedSkillRepo.findAll();
	}

	@GetMapping("/auto-check-rules")
	public ApiResponse<List<Object>> listAutoCheckRules() {
		// Currently empty in prod (pipeline_auto_check_triggers = 0 rows)
		return ApiResponse.ok(List.of());
	}
}
