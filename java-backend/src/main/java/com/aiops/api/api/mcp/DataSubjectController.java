package com.aiops.api.api.mcp;

import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.mcp.DataSubjectEntity;
import com.aiops.api.domain.mcp.DataSubjectRepository;
import jakarta.validation.constraints.NotBlank;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1/data-subjects")
public class DataSubjectController {

	private final DataSubjectRepository repository;

	public DataSubjectController(DataSubjectRepository repository) {
		this.repository = repository;
	}

	@GetMapping
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<Dtos.Detail>> list() {
		return ApiResponse.ok(repository.findAll().stream().map(Dtos::of).toList());
	}

	@GetMapping("/{id}")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Dtos.Detail> get(@PathVariable Long id) {
		return ApiResponse.ok(Dtos.of(repository.findById(id)
				.orElseThrow(() -> ApiException.notFound("data subject"))));
	}

	@PostMapping
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<Dtos.Detail> create(@Validated @RequestBody Dtos.CreateRequest req) {
		if (repository.findByName(req.name()).isPresent()) {
			throw ApiException.conflict("data subject name already exists");
		}
		DataSubjectEntity e = new DataSubjectEntity();
		e.setName(req.name());
		if (req.description() != null) e.setDescription(req.description());
		if (req.apiConfig() != null) e.setApiConfig(req.apiConfig());
		if (req.inputSchema() != null) e.setInputSchema(req.inputSchema());
		if (req.outputSchema() != null) e.setOutputSchema(req.outputSchema());
		return ApiResponse.ok(Dtos.of(repository.save(e)));
	}

	@PutMapping("/{id}")
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<Dtos.Detail> update(@PathVariable Long id,
	                                       @Validated @RequestBody Dtos.UpdateRequest req) {
		DataSubjectEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("data subject"));
		if (Boolean.TRUE.equals(e.getIsBuiltin())) {
			throw ApiException.conflict("builtin data subject cannot be modified");
		}
		if (req.description() != null) e.setDescription(req.description());
		if (req.apiConfig() != null) e.setApiConfig(req.apiConfig());
		if (req.inputSchema() != null) e.setInputSchema(req.inputSchema());
		if (req.outputSchema() != null) e.setOutputSchema(req.outputSchema());
		return ApiResponse.ok(Dtos.of(repository.save(e)));
	}

	@DeleteMapping("/{id}")
	@Transactional
	@PreAuthorize(Authorities.ADMIN)
	public ApiResponse<Void> delete(@PathVariable Long id) {
		DataSubjectEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("data subject"));
		if (Boolean.TRUE.equals(e.getIsBuiltin())) {
			throw ApiException.conflict("builtin data subject cannot be deleted");
		}
		repository.delete(e);
		return ApiResponse.ok(null);
	}

	public static final class Dtos {

		public record Detail(Long id, String name, String description, String apiConfig,
		                     String inputSchema, String outputSchema, Boolean isBuiltin,
		                     java.time.OffsetDateTime updatedAt) {}

		public record CreateRequest(@NotBlank String name, String description, String apiConfig,
		                            String inputSchema, String outputSchema) {}

		public record UpdateRequest(String description, String apiConfig, String inputSchema,
		                            String outputSchema) {}

		static Detail of(DataSubjectEntity e) {
			return new Detail(e.getId(), e.getName(), e.getDescription(), e.getApiConfig(),
					e.getInputSchema(), e.getOutputSchema(), e.getIsBuiltin(), e.getUpdatedAt());
		}
	}
}
