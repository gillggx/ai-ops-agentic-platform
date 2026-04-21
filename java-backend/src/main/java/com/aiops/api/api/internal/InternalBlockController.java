package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.pipeline.BlockEntity;
import com.aiops.api.domain.pipeline.BlockRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/** Block definitions for the pipeline executor + agent_builder inside the sidecar. */
@RestController
@RequestMapping("/internal/blocks")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalBlockController {

	private final BlockRepository repository;

	public InternalBlockController(BlockRepository repository) {
		this.repository = repository;
	}

	@GetMapping
	public ApiResponse<List<Dto>> list(@RequestParam(required = false) String category,
	                                   @RequestParam(required = false) String status) {
		List<BlockEntity> all;
		if (category != null && !category.isBlank()) {
			all = repository.findByCategory(category);
		} else if (status != null && !status.isBlank()) {
			all = repository.findByStatus(status);
		} else {
			all = repository.findAll();
		}
		return ApiResponse.ok(all.stream().map(Dto::of).toList());
	}

	@GetMapping("/{id}")
	public ApiResponse<Dto> get(@PathVariable Long id) {
		return ApiResponse.ok(Dto.of(repository.findById(id)
				.orElseThrow(() -> ApiException.notFound("block"))));
	}

	public record Dto(Long id, String name, String category, String version, String status,
	                  String description, String inputSchema, String outputSchema,
	                  String paramSchema, String implementation, String examples,
	                  String outputColumnsHint, Boolean isCustom) {
		static Dto of(BlockEntity e) {
			return new Dto(e.getId(), e.getName(), e.getCategory(), e.getVersion(), e.getStatus(),
					e.getDescription(), e.getInputSchema(), e.getOutputSchema(),
					e.getParamSchema(), e.getImplementation(), e.getExamples(),
					e.getOutputColumnsHint(), e.getIsCustom());
		}
	}
}
