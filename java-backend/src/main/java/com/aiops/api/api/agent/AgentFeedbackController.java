package com.aiops.api.api.agent;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.agent.AgentFeedbackLogEntity;
import com.aiops.api.domain.agent.AgentFeedbackLogRepository;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.PageRequest;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Set;

/**
 * 👍 / 👎 feedback on individual agent answers (synthesis events).
 *
 * <p>Users rate their own messages — write path is open to any authenticated
 * role. The admin readout (used to drive the Evaluation dashboard, P1) is
 * IT_ADMIN-only.
 *
 * <p>Same (session_id, message_idx, user_id) tuple upserts so the user can
 * change their mind without inflating the log.
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/agent/feedback")
public class AgentFeedbackController {

	private static final Set<String> ALLOWED_REASONS = Set.of(
			"data_wrong", "logic_wrong", "chart_unclear");

	private static final int MAX_LIMIT = 500;

	private final AgentFeedbackLogRepository repository;

	public AgentFeedbackController(AgentFeedbackLogRepository repository) {
		this.repository = repository;
	}

	/** Record a rating. Pass {@code rating=1} for 👍, {@code rating=-1} for 👎. */
	@PostMapping
	@PreAuthorize(Authorities.ANY_ROLE)
	@Transactional
	public ApiResponse<FeedbackDto> create(@Validated @RequestBody CreateFeedbackRequest req,
	                                        @AuthenticationPrincipal AuthPrincipal actor) {
		if (actor == null) {
			throw ApiException.forbidden("login required");
		}
		if (req.rating() != 1 && req.rating() != -1) {
			throw ApiException.badRequest("rating must be 1 (👍) or -1 (👎)");
		}
		if (req.rating() == -1) {
			if (req.reason() == null || req.reason().isBlank()) {
				throw ApiException.badRequest("reason required when rating is 👎");
			}
			if (!ALLOWED_REASONS.contains(req.reason())) {
				throw ApiException.badRequest("reason must be one of " + ALLOWED_REASONS);
			}
		}

		Long uid = Long.valueOf(actor.userId());
		AgentFeedbackLogEntity entity = repository
				.findBySessionIdAndMessageIdxAndUserId(req.sessionId(), req.messageIdx(), uid)
				.orElseGet(AgentFeedbackLogEntity::new);

		entity.setSessionId(req.sessionId());
		entity.setUserId(uid);
		entity.setMessageIdx(req.messageIdx());
		entity.setRating((short) (int) req.rating());
		entity.setReason(req.rating() == 1 ? null : req.reason());
		entity.setFreeText(truncate(req.freeText(), 500));
		entity.setContractSummary(req.contractSummary());
		entity.setToolsUsed(req.toolsUsed());

		AgentFeedbackLogEntity saved = repository.save(entity);
		log.info("agent feedback session={} msg={} user={} rating={} reason={}",
				saved.getSessionId(), saved.getMessageIdx(), saved.getUserId(),
				saved.getRating(), saved.getReason());
		return ApiResponse.ok(FeedbackDto.of(saved));
	}

	/** Admin readout — for the Evaluation dashboard (P1). */
	@GetMapping
	@PreAuthorize(Authorities.ADMIN)
	public ApiResponse<List<FeedbackDto>> list(
			@RequestParam(required = false) OffsetDateTime since,
			@RequestParam(defaultValue = "100") int limit) {
		int safe = Math.min(Math.max(limit, 1), MAX_LIMIT);
		var page = PageRequest.of(0, safe);
		var rows = (since != null)
				? repository.findRecentSince(since, page)
				: repository.findRecentAll(page);
		return ApiResponse.ok(rows.stream().map(FeedbackDto::of).toList());
	}

	private static String truncate(String s, int max) {
		if (s == null) return null;
		String trimmed = s.strip();
		return trimmed.length() <= max ? trimmed : trimmed.substring(0, max);
	}

	// ── DTOs ──────────────────────────────────────────────────────────

	public record CreateFeedbackRequest(
			@NotBlank String sessionId,
			@NotNull @Min(0) Integer messageIdx,
			@NotNull Integer rating,
			String reason,
			String freeText,
			String contractSummary,
			String toolsUsed) {}

	public record FeedbackDto(Long id, String sessionId, Long userId, Integer messageIdx,
	                           Integer rating, String reason, String freeText,
	                           String contractSummary, String toolsUsed,
	                           OffsetDateTime createdAt) {
		static FeedbackDto of(AgentFeedbackLogEntity e) {
			return new FeedbackDto(
					e.getId(), e.getSessionId(), e.getUserId(), e.getMessageIdx(),
					e.getRating() == null ? null : (int) e.getRating(),
					e.getReason(), e.getFreeText(),
					e.getContractSummary(), e.getToolsUsed(),
					e.getCreatedAt());
		}
	}
}
