package com.aiops.api.api.internal;

import com.aiops.api.domain.agentknowledge.AgentDirectiveEntity;
import com.aiops.api.domain.agentknowledge.AgentDirectiveFireEntity;
import com.aiops.api.domain.agentknowledge.AgentDirectiveFireRepository;
import com.aiops.api.domain.agentknowledge.AgentDirectiveRepository;
import com.aiops.api.domain.agentknowledge.AgentExampleEntity;
import com.aiops.api.domain.agentknowledge.AgentExampleRepository;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeEntity;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeRepository;
import com.aiops.api.domain.agentknowledge.AgentLexiconEntity;
import com.aiops.api.domain.agentknowledge.AgentLexiconRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

/**
 * Internal (sidecar-only) Agent Knowledge business logic — RAG search,
 * embedding backfill writes, usage bumps, missing-embedding listing.
 *
 * <p>Extracted from {@link InternalAgentKnowledgeController} 2026-05-23
 * as part of the Phase 12 OOP refactor. Stays separate from
 * {@code AgentKnowledgeService} (the public CRUD path) because the
 * concerns are different: this service is sidecar-driven, cross-user,
 * and centred on RAG lookup + embedding lifecycle; the public service
 * is user-scoped CRUD with ownership checks.
 *
 * <p>All embedding writes go through native SQL on the repository
 * ({@code updateEmbedding} / {@code clearEmbedding}) — see the fix in
 * commit e03020d for why JPA save() can't bind pgvector columns.
 */
@Service
@RequiredArgsConstructor
public class InternalAgentKnowledgeService {

	private final AgentDirectiveRepository directiveRepo;
	private final AgentDirectiveFireRepository fireRepo;
	private final AgentLexiconRepository lexiconRepo;
	private final AgentKnowledgeRepository knowledgeRepo;
	private final AgentExampleRepository exampleRepo;

	// ══════════════════════════════════════════════════════════════════════
	// Directives
	// ══════════════════════════════════════════════════════════════════════

	public List<AgentDirectiveEntity> activeDirectives(Long userId, String skillSlug,
	                                                    String toolId, String recipeId,
	                                                    int limit) {
		return directiveRepo.findActiveForScope(userId, skillSlug, toolId, recipeId, limit);
	}

	@Transactional
	public Map<String, Object> recordFire(Long directiveId, String sessionId, String context) {
		if (!directiveRepo.existsById(directiveId)) {
			return Map.of("recorded", false, "reason", "directive not found");
		}
		AgentDirectiveFireEntity e = new AgentDirectiveFireEntity();
		e.setDirectiveId(directiveId);
		e.setSessionId(sessionId);
		e.setContext(context);
		fireRepo.save(e);
		return Map.of("recorded", true, "id", e.getId());
	}

	// ══════════════════════════════════════════════════════════════════════
	// Lexicon
	// ══════════════════════════════════════════════════════════════════════

	public List<AgentLexiconEntity> lexicon(Long userId) {
		return lexiconRepo.findByUserIdOrderByUsesDescTermAsc(userId);
	}

	@Transactional
	public Map<String, Object> bumpLexiconUse(Long id) {
		AgentLexiconEntity e = lexiconRepo.findById(id).orElse(null);
		if (e == null) return Map.of("bumped", false);
		e.setUses(e.getUses() + 1);
		e.setUpdatedAt(OffsetDateTime.now());
		return Map.of("bumped", true, "uses", e.getUses());
	}

	// ══════════════════════════════════════════════════════════════════════
	// Knowledge (RAG)
	// ══════════════════════════════════════════════════════════════════════

	/** Sidecar passes a vector literal "[v1,v2,...]" computed from query.
	 *  V58: {@code layer} ('plan'|'execute'|null) filters by applies_to so the
	 *  plan and execute agent layers retrieve different slices. */
	public List<AgentKnowledgeEntity> searchKnowledge(Long userId, String queryVec,
	                                                   String skillSlug, String toolId, String recipeId,
	                                                   String layer, Integer limit) {
		if (queryVec == null || queryVec.isBlank()) {
			return List.of();
		}
		String layerFilter = (layer == null || layer.isBlank()) ? null : layer;
		return knowledgeRepo.searchByEmbedding(
				userId, queryVec, skillSlug, toolId, recipeId,
				layerFilter, limit != null ? limit : 3);
	}

	/** PUT embedding for a knowledge row (called by sidecar after async embed).
	 *  Uses the repository's native {@code CAST(?vec AS vector)} UPDATE — see
	 *  commit e03020d for why JPA save() rejects pgvector columns. */
	@Transactional
	public Map<String, Object> setKnowledgeEmbedding(Long id, String vec) {
		if (vec == null || vec.isBlank()) {
			return Map.of("updated", false, "reason", "empty embedding");
		}
		int affected = knowledgeRepo.updateEmbedding(id, vec);
		return Map.of("updated", affected > 0, "affected", affected);
	}

	@Transactional
	public Map<String, Object> bumpKnowledgeUse(Long id) {
		AgentKnowledgeEntity e = knowledgeRepo.findById(id).orElse(null);
		if (e == null) return Map.of("bumped", false);
		e.setUses(e.getUses() + 1);
		e.setLastUsedAt(OffsetDateTime.now());
		return Map.of("bumped", true, "uses", e.getUses());
	}

	/** List rows missing embedding so sidecar can backfill on a schedule. */
	public List<AgentKnowledgeEntity> missingKnowledgeEmbeddings(int limit) {
		// simplest: filter list-all for null embedding; small dataset OK
		return knowledgeRepo.findAll().stream()
				.filter(e -> e.getEmbedding() == null)
				.limit(limit)
				.toList();
	}

	/** Return global high-priority knowledge regardless of embedding
	 *  similarity. Multilingual recall on long Chinese queries is patchy
	 *  (verified empirically), so high-priority "first principle" entries must
	 *  reach the planner UNCONDITIONALLY, not gated on RAG cosine match.
	 *  Small dataset (&lt;30 high-priority rows expected) — full scan OK.
	 *
	 *  <p>V58: {@code layer} ('plan'|'execute'|null) filters by applies_to;
	 *  {@code alwaysOnly} narrows to always_on=true (the irreducible core) so
	 *  the plan prompt can shrink from "all 19 high bodies" to "core + RAG". */
	public List<AgentKnowledgeEntity> highPriorityKnowledge(Long userId, int limit,
	                                                        String layer, boolean alwaysOnly) {
		final String layerFilter = (layer == null || layer.isBlank()) ? null : layer;
		return knowledgeRepo.findAll().stream()
				.filter(e -> e.getActive() != null && e.getActive())
				.filter(e -> "high".equalsIgnoreCase(e.getPriority()))
				.filter(e -> "global".equals(e.getScopeType())
				          || (e.getUserId() != null && e.getUserId().equals(userId)))
				.filter(e -> layerFilter == null
				          || layerFilter.equals(e.getAppliesTo())
				          || "both".equals(e.getAppliesTo()))
				.filter(e -> !alwaysOnly || Boolean.TRUE.equals(e.getAlwaysOn()))
				.limit(limit)
				.toList();
	}

	// ══════════════════════════════════════════════════════════════════════
	// Examples (few-shot)
	// ══════════════════════════════════════════════════════════════════════

	public List<AgentExampleEntity> searchExamples(Long userId, String queryVec,
	                                                String skillSlug, String toolId, String recipeId,
	                                                Integer limit) {
		if (queryVec == null || queryVec.isBlank()) {
			return List.of();
		}
		return exampleRepo.searchByEmbedding(
				userId, queryVec, skillSlug, toolId, recipeId,
				limit != null ? limit : 2);
	}

	@Transactional
	public Map<String, Object> setExampleEmbedding(Long id, String vec) {
		// Same pgvector caveat as setKnowledgeEmbedding — use native cast.
		if (vec == null || vec.isBlank()) {
			return Map.of("updated", false, "reason", "empty embedding");
		}
		int affected = exampleRepo.updateEmbedding(id, vec);
		return Map.of("updated", affected > 0, "affected", affected);
	}

	public List<AgentExampleEntity> missingExampleEmbeddings(int limit) {
		return exampleRepo.findAll().stream()
				.filter(e -> e.getEmbedding() == null)
				.limit(limit)
				.toList();
	}
}
