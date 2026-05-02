package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.pipeline.PublishedSkillEntity;
import com.aiops.api.domain.pipeline.PublishedSkillRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * Internal search surface for the Python sidecar's {@code search_published_skills}
 * and {@code _invoke_published_skill} agent tools. Mirrors the public
 * PipelineBuilderController endpoint but accepts the X-Internal-Token used by
 * the sidecar's JavaAPIClient instead of a user JWT.
 *
 * <p>Naive case-insensitive substring scoring across name / use_case /
 * when_to_use / tags / slug. Good enough for the small registry until
 * pgvector embeddings ship.
 */
@RestController
@RequestMapping("/internal/published-skills")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalPublishedSkillController {

	private final PublishedSkillRepository repo;

	public InternalPublishedSkillController(PublishedSkillRepository repo) {
		this.repo = repo;
	}

	@PostMapping("/search")
	public ApiResponse<List<PublishedSkillEntity>> search(@RequestBody SearchRequest req) {
		final String q = (req == null || req.query() == null) ? "" : req.query().trim().toLowerCase();
		final int topK = (req == null || req.topK() == null || req.topK() <= 0)
				? 5
				: Math.min(req.topK(), 50);

		List<PublishedSkillEntity> active = repo.findByStatus("active");
		if (q.isEmpty()) {
			return ApiResponse.ok(active.stream()
					.sorted((a, b) -> a.getName().compareToIgnoreCase(b.getName()))
					.limit(topK)
					.toList());
		}

		final String[] terms = q.split("\\s+");
		return ApiResponse.ok(active.stream()
				.map(skill -> Map.entry(skill, scoreSkill(skill, terms)))
				.filter(e -> e.getValue() > 0)
				.sorted((a, b) -> Integer.compare(b.getValue(), a.getValue()))
				.limit(topK)
				.map(Map.Entry::getKey)
				.toList());
	}

	private static int scoreSkill(PublishedSkillEntity s, String[] terms) {
		String hay = (
				(s.getName() == null ? "" : s.getName()) + " " +
				(s.getUseCase() == null ? "" : s.getUseCase()) + " " +
				(s.getWhenToUse() == null ? "" : s.getWhenToUse()) + " " +
				(s.getTags() == null ? "" : s.getTags()) + " " +
				(s.getSlug() == null ? "" : s.getSlug())
		).toLowerCase();
		int score = 0;
		for (String t : terms) {
			if (t.isBlank()) continue;
			int idx = 0;
			while ((idx = hay.indexOf(t, idx)) >= 0) {
				score++;
				idx += t.length();
			}
		}
		return score;
	}

	public record SearchRequest(
			String query,
			@com.fasterxml.jackson.annotation.JsonProperty("top_k") Integer topK
	) {}
}
