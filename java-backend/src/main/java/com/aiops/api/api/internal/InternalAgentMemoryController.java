package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.agent.AgentMemoryEntity;
import com.aiops.api.domain.agent.AgentMemoryRepository;
import jakarta.validation.constraints.NotBlank;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * Agent memory store used by LangGraph. Write path from the sidecar;
 * read path serves recall (no vector sim yet — Phase 7 adds pgvector
 * similarity search endpoint).
 */
@RestController
@RequestMapping("/internal/agent-memories")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalAgentMemoryController {

	private final AgentMemoryRepository repository;

	public InternalAgentMemoryController(AgentMemoryRepository repository) {
		this.repository = repository;
	}

	@PostMapping
	@Transactional
	public ApiResponse<Dto> create(@Validated @RequestBody CreateRequest req) {
		AgentMemoryEntity e = new AgentMemoryEntity();
		e.setUserId(req.userId());
		e.setContent(req.content());
		e.setEmbedding(req.embedding());
		e.setSource(req.source());
		e.setRefId(req.refId());
		e.setTaskType(req.taskType());
		e.setDataSubject(req.dataSubject());
		e.setToolName(req.toolName());
		return ApiResponse.ok(Dto.of(repository.save(e)));
	}

	@GetMapping
	public ApiResponse<List<Dto>> list(@RequestParam Long userId,
	                                   @RequestParam(required = false) String taskType) {
		List<AgentMemoryEntity> all = (taskType != null && !taskType.isBlank())
				? repository.findByUserIdAndTaskType(userId, taskType)
				: repository.findByUserIdOrderByCreatedAtDesc(userId);
		return ApiResponse.ok(all.stream().map(Dto::of).toList());
	}

	public record CreateRequest(@jakarta.validation.constraints.NotNull Long userId,
	                            @NotBlank String content, String embedding, String source,
	                            String refId, String taskType, String dataSubject, String toolName) {}

	public record Dto(Long id, Long userId, String content, String source, String refId,
	                  String taskType, String dataSubject, String toolName,
	                  java.time.OffsetDateTime createdAt) {
		static Dto of(AgentMemoryEntity e) {
			return new Dto(e.getId(), e.getUserId(), e.getContent(), e.getSource(), e.getRefId(),
					e.getTaskType(), e.getDataSubject(), e.getToolName(), e.getCreatedAt());
		}
	}
}
