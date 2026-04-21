package com.aiops.api.api.mcp;

import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.mcp.MockDataSourceEntity;
import com.aiops.api.domain.mcp.MockDataSourceRepository;
import jakarta.validation.constraints.NotBlank;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1/mock-data-sources")
public class MockDataSourceController {

	private final MockDataSourceRepository repository;

	public MockDataSourceController(MockDataSourceRepository repository) {
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
				.orElseThrow(() -> ApiException.notFound("mock data source"))));
	}

	@PostMapping
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<Dtos.Detail> create(@Validated @RequestBody Dtos.CreateRequest req) {
		if (repository.findByName(req.name()).isPresent()) {
			throw ApiException.conflict("mock data source name already exists");
		}
		MockDataSourceEntity e = new MockDataSourceEntity();
		e.setName(req.name());
		if (req.description() != null) e.setDescription(req.description());
		if (req.inputSchema() != null) e.setInputSchema(req.inputSchema());
		if (req.pythonCode() != null) e.setPythonCode(req.pythonCode());
		if (req.sampleOutput() != null) e.setSampleOutput(req.sampleOutput());
		return ApiResponse.ok(Dtos.of(repository.save(e)));
	}

	@PutMapping("/{id}")
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<Dtos.Detail> update(@PathVariable Long id,
	                                       @Validated @RequestBody Dtos.UpdateRequest req) {
		MockDataSourceEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("mock data source"));
		if (req.description() != null) e.setDescription(req.description());
		if (req.inputSchema() != null) e.setInputSchema(req.inputSchema());
		if (req.pythonCode() != null) e.setPythonCode(req.pythonCode());
		if (req.sampleOutput() != null) e.setSampleOutput(req.sampleOutput());
		if (req.isActive() != null) e.setIsActive(req.isActive());
		return ApiResponse.ok(Dtos.of(repository.save(e)));
	}

	@DeleteMapping("/{id}")
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<Void> delete(@PathVariable Long id) {
		if (!repository.existsById(id)) throw ApiException.notFound("mock data source");
		repository.deleteById(id);
		return ApiResponse.ok(null);
	}

	public static final class Dtos {

		public record Detail(Long id, String name, String description, String inputSchema,
		                     String pythonCode, String sampleOutput, Boolean isActive,
		                     java.time.OffsetDateTime updatedAt) {}

		public record CreateRequest(@NotBlank String name, String description, String inputSchema,
		                            String pythonCode, String sampleOutput) {}

		public record UpdateRequest(String description, String inputSchema, String pythonCode,
		                            String sampleOutput, Boolean isActive) {}

		static Detail of(MockDataSourceEntity e) {
			return new Detail(e.getId(), e.getName(), e.getDescription(), e.getInputSchema(),
					e.getPythonCode(), e.getSampleOutput(), e.getIsActive(), e.getUpdatedAt());
		}
	}
}
