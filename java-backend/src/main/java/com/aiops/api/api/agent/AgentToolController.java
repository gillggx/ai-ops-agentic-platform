package com.aiops.api.api.agent;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.agent.AgentToolEntity;
import com.aiops.api.domain.agent.AgentToolRepository;
import jakarta.validation.constraints.NotBlank;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/** Per-user agent tools (user owns its rows, PE+ADMIN visible only to their own). */
@RestController
@RequestMapping("/api/v1/agent-tools")
@PreAuthorize(Authorities.ADMIN_OR_PE)
public class AgentToolController {

	private final AgentToolRepository repository;

	public AgentToolController(AgentToolRepository repository) {
		this.repository = repository;
	}

	@GetMapping
	public ApiResponse<List<Dtos.Detail>> listMyTools(@AuthenticationPrincipal AuthPrincipal caller) {
		return ApiResponse.ok(repository.findByUserIdOrderByUpdatedAtDesc(caller.userId())
				.stream().map(Dtos::of).toList());
	}

	@GetMapping("/{id}")
	public ApiResponse<Dtos.Detail> get(@PathVariable Long id,
	                                    @AuthenticationPrincipal AuthPrincipal caller) {
		AgentToolEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("agent tool"));
		requireOwner(e, caller);
		return ApiResponse.ok(Dtos.of(e));
	}

	@PostMapping
	@Transactional
	public ApiResponse<Dtos.Detail> create(@Validated @RequestBody Dtos.CreateRequest req,
	                                       @AuthenticationPrincipal AuthPrincipal caller) {
		AgentToolEntity e = new AgentToolEntity();
		e.setUserId(caller.userId());
		e.setName(req.name());
		e.setCode(req.code());
		if (req.description() != null) e.setDescription(req.description());
		return ApiResponse.ok(Dtos.of(repository.save(e)));
	}

	@PutMapping("/{id}")
	@Transactional
	public ApiResponse<Dtos.Detail> update(@PathVariable Long id,
	                                       @Validated @RequestBody Dtos.UpdateRequest req,
	                                       @AuthenticationPrincipal AuthPrincipal caller) {
		AgentToolEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("agent tool"));
		requireOwner(e, caller);
		if (req.code() != null) e.setCode(req.code());
		if (req.description() != null) e.setDescription(req.description());
		return ApiResponse.ok(Dtos.of(repository.save(e)));
	}

	@DeleteMapping("/{id}")
	@Transactional
	public ApiResponse<Void> delete(@PathVariable Long id,
	                                @AuthenticationPrincipal AuthPrincipal caller) {
		AgentToolEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("agent tool"));
		requireOwner(e, caller);
		repository.delete(e);
		return ApiResponse.ok(null);
	}

	private void requireOwner(AgentToolEntity e, AuthPrincipal caller) {
		if (!caller.userId().equals(e.getUserId())) {
			throw ApiException.forbidden("not your agent tool");
		}
	}

	public static final class Dtos {

		public record Detail(Long id, Long userId, String name, String description, String code,
		                     Integer usageCount, java.time.OffsetDateTime updatedAt) {}

		public record CreateRequest(@NotBlank String name, @NotBlank String code, String description) {}

		public record UpdateRequest(String code, String description) {}

		static Detail of(AgentToolEntity e) {
			return new Detail(e.getId(), e.getUserId(), e.getName(), e.getDescription(),
					e.getCode(), e.getUsageCount(), e.getUpdatedAt());
		}
	}
}
