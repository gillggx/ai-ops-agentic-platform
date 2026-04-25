package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.agent.AgentExperienceMemoryEntity;
import com.aiops.api.domain.agent.AgentExperienceMemoryRepository;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * Reflective long-term memory store (agent_experience_memory).
 *
 * <p>Used by the Python sidecar's {@code memory_lifecycle} +
 * {@code load_context} nodes to (1) write abstracted experience memories
 * with bge-m3 embeddings, (2) semantically search them at retrieve time,
 * and (3) record success/fail feedback against past retrievals.
 *
 * <p>The sidecar computes embeddings (via Ollama) and ships the
 * {@code float[1024]} vector here; we serialize it to the pgvector
 * {@code '[...]'::vector} literal and run the cosine search.
 */
@Slf4j
@RestController
@RequestMapping("/internal/agent-experience-memories")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalAgentExperienceMemoryController {

	/** confidence_score column max — matches DEFAULT_CONFIDENCE+ in Python service. */
	private static final int MAX_CONFIDENCE = 10;

	private final AgentExperienceMemoryRepository repository;

	public InternalAgentExperienceMemoryController(AgentExperienceMemoryRepository repository) {
		this.repository = repository;
	}

	/**
	 * Semantic search by embedding. Returns top-K closest memories.
	 * Sidecar passes 1024-dim float vector + min_similarity / min_confidence
	 * thresholds; we run pgvector cosine and filter.
	 */
	@PostMapping("/search")
	public ApiResponse<List<SearchHit>> search(@Validated @RequestBody SearchRequest req) {
		String vecLit = toVectorLiteral(req.queryEmbedding());
		List<Object[]> rows = repository.searchByEmbedding(
				req.userId(), vecLit, req.topK(), req.minConfidence());

		double minSim = req.minSimilarity();
		List<SearchHit> hits = rows.stream()
				.map(row -> new SearchHit(MemoryDto.of((AgentExperienceMemoryEntity) row[0]),
						((Number) row[1]).doubleValue()))
				.filter(h -> h.similarity() >= minSim)
				.toList();
		return ApiResponse.ok(hits);
	}

	/**
	 * Write a new experience memory with optional embedding-based dedup.
	 * If {@code dedupThreshold} is non-null and a near-duplicate exists,
	 * its {@code confidence_score} is bumped instead of inserting a new row.
	 */
	@PostMapping
	@Transactional
	public ApiResponse<WriteResult> write(@Validated @RequestBody WriteRequest req) {
		String vecLit = (req.embedding() != null && !req.embedding().isEmpty())
				? toVectorLiteral(req.embedding()) : null;

		// Dedup check
		if (vecLit != null && req.dedupThreshold() != null) {
			List<Object[]> nearest = repository.findNearestForDedup(req.userId(), vecLit);
			if (!nearest.isEmpty()) {
				AgentExperienceMemoryEntity dup = (AgentExperienceMemoryEntity) nearest.get(0)[0];
				double sim = ((Number) nearest.get(0)[1]).doubleValue();
				if (sim >= req.dedupThreshold()) {
					repository.bumpConfidence(dup.getId(), MAX_CONFIDENCE);
					AgentExperienceMemoryEntity refreshed = repository.findById(dup.getId())
							.orElseThrow(() -> ApiException.notFound("memory"));
					log.info("dedup hit user={} id={} sim={}", req.userId(), dup.getId(),
							String.format("%.3f", sim));
					return ApiResponse.ok(new WriteResult(MemoryDto.of(refreshed), true, sim));
				}
			}
		}

		AgentExperienceMemoryEntity m = new AgentExperienceMemoryEntity();
		m.setUserId(req.userId());
		m.setIntentSummary(truncate(req.intentSummary(), 500));
		m.setAbstractAction(req.abstractAction());
		m.setEmbedding(vecLit);
		m.setConfidenceScore(req.confidenceScore() != null ? req.confidenceScore() : 5);
		m.setStatus("ACTIVE");
		m.setSource(req.source() != null ? req.source() : "auto");
		m.setSourceSessionId(req.sourceSessionId());
		m = repository.save(m);
		log.info("memory written user={} id={} intent={}", req.userId(), m.getId(),
				truncate(req.intentSummary(), 60));
		return ApiResponse.ok(new WriteResult(MemoryDto.of(m), false, 0.0));
	}

	/**
	 * Record feedback on a memory previously retrieved + cited (or passively
	 * credited). Bumps success_count or fail_count; updates last_used_at.
	 */
	@PutMapping("/{id}/feedback")
	@Transactional
	public ApiResponse<MemoryDto> feedback(@PathVariable Long id,
	                                        @Validated @RequestBody FeedbackRequest req) {
		boolean success = "success".equalsIgnoreCase(req.outcome());
		boolean fail = "fail".equalsIgnoreCase(req.outcome());
		if (!success && !fail) {
			throw ApiException.badRequest("outcome must be 'success' or 'fail'");
		}
		int updated = repository.recordFeedback(id, success ? 1 : 0, fail ? 1 : 0);
		if (updated == 0) {
			throw ApiException.notFound("memory");
		}
		AgentExperienceMemoryEntity m = repository.findById(id)
				.orElseThrow(() -> ApiException.notFound("memory"));
		return ApiResponse.ok(MemoryDto.of(m));
	}

	/** Plain list by user — for the legacy /api/v1/experience-memory listing path. */
	@GetMapping
	public ApiResponse<List<MemoryDto>> list(@RequestParam Long userId,
	                                          @RequestParam(required = false, defaultValue = "ACTIVE") String status) {
		var rows = repository.findByUserIdAndStatusOrderByLastUsedAtDesc(userId, status);
		return ApiResponse.ok(rows.stream().map(MemoryDto::of).toList());
	}

	// ── helpers ────────────────────────────────────────────────────────

	/**
	 * Format a float vector as a pgvector literal: "[1.0,2.0,3.0,...]".
	 * This is what {@code CAST(? AS vector)} expects.
	 */
	private static String toVectorLiteral(List<Double> vec) {
		StringBuilder sb = new StringBuilder(vec.size() * 8 + 2);
		sb.append('[');
		for (int i = 0; i < vec.size(); i++) {
			if (i > 0) sb.append(',');
			sb.append(vec.get(i));
		}
		sb.append(']');
		return sb.toString();
	}

	private static String truncate(String s, int max) {
		if (s == null) return null;
		String trimmed = s.strip();
		return trimmed.length() <= max ? trimmed : trimmed.substring(0, max);
	}

	// ── DTOs ──────────────────────────────────────────────────────────

	public record SearchRequest(@NotNull Long userId,
	                             @NotEmpty List<Double> queryEmbedding,
	                             int topK,
	                             double minSimilarity,
	                             int minConfidence) {
		public SearchRequest {
			if (topK <= 0) topK = 5;
			if (minConfidence < 0) minConfidence = 0;
		}
	}

	public record WriteRequest(@NotNull Long userId,
	                            @NotBlank String intentSummary,
	                            @NotBlank String abstractAction,
	                            List<Double> embedding,
	                            String source,
	                            String sourceSessionId,
	                            Integer confidenceScore,
	                            Double dedupThreshold) {}

	public record FeedbackRequest(@NotBlank String outcome) {}

	public record SearchHit(MemoryDto memory, double similarity) {}

	public record WriteResult(MemoryDto memory, boolean dedupHit, double similarity) {}

	public record MemoryDto(Long id, Long userId, String intentSummary, String abstractAction,
	                         Integer confidenceScore, Integer useCount, Integer successCount,
	                         Integer failCount, String status, String source,
	                         String sourceSessionId, OffsetDateTime lastUsedAt,
	                         OffsetDateTime createdAt) {
		static MemoryDto of(AgentExperienceMemoryEntity e) {
			return new MemoryDto(e.getId(), e.getUserId(), e.getIntentSummary(), e.getAbstractAction(),
					e.getConfidenceScore(), e.getUseCount(), e.getSuccessCount(), e.getFailCount(),
					e.getStatus(), e.getSource(), e.getSourceSessionId(),
					e.getLastUsedAt(), e.getCreatedAt());
		}
	}
}
