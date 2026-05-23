package com.aiops.api.api.internal;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.agentknowledge.AgentDirectiveEntity;
import com.aiops.api.domain.agentknowledge.AgentExampleEntity;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeEntity;
import com.aiops.api.domain.agentknowledge.AgentLexiconEntity;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * Sidecar-only endpoints for retrieving agent knowledge during context_load.
 *
 * <p>The user-facing controller (/api/v1/agent-*) handles CRUD with auth;
 * this internal controller exposes scope-filtered queries for the sidecar
 * to fetch directives / knowledge / lexicon / examples relevant to the
 * current conversation, plus update endpoints for embeddings + usage stats.
 *
 * <p>2026-05-23 (Phase 12 OOP refactor): business logic (existence checks,
 * RAG search wiring, embedding cast, missing-embedding filter,
 * high-priority full-scan) moved to {@link InternalAgentKnowledgeService}.
 * Lite DTOs stayed nested here — used only by this controller, extraction
 * would be ceremony.
 */
@RestController
@RequestMapping("/internal/agent-knowledge")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
@RequiredArgsConstructor
public class InternalAgentKnowledgeController {

	private final InternalAgentKnowledgeService service;

	// ── Directives ────────────────────────────────────────────────────────

	@GetMapping("/directives/active")
	public ApiResponse<List<DirectiveLite>> activeDirectives(
			@RequestParam("user_id") Long userId,
			@RequestParam(value = "skill_slug", required = false) String skillSlug,
			@RequestParam(value = "tool_id",   required = false) String toolId,
			@RequestParam(value = "recipe_id", required = false) String recipeId,
			@RequestParam(value = "limit", defaultValue = "8") int limit) {
		return ApiResponse.ok(service.activeDirectives(userId, skillSlug, toolId, recipeId, limit)
				.stream().map(DirectiveLite::of).toList());
	}

	@PostMapping("/directives/{id}/fire")
	public ApiResponse<Map<String, Object>> recordFire(@PathVariable("id") Long directiveId,
	                                                    @RequestBody Map<String, String> body) {
		return ApiResponse.ok(service.recordFire(directiveId, body.get("session_id"), body.get("context")));
	}

	// ── Lexicon ───────────────────────────────────────────────────────────

	@GetMapping("/lexicon")
	public ApiResponse<List<LexiconLite>> lexicon(@RequestParam("user_id") Long userId) {
		return ApiResponse.ok(service.lexicon(userId).stream().map(LexiconLite::of).toList());
	}

	@PostMapping("/lexicon/{id}/use")
	public ApiResponse<Map<String, Object>> bumpLexiconUse(@PathVariable Long id) {
		return ApiResponse.ok(service.bumpLexiconUse(id));
	}

	// ── Knowledge (RAG) ───────────────────────────────────────────────────

	@PostMapping("/knowledge/search")
	public ApiResponse<List<KnowledgeLite>> searchKnowledge(@RequestBody KnowledgeSearchRequest req) {
		return ApiResponse.ok(service.searchKnowledge(req.userId(), req.queryVec(),
				req.skillSlug(), req.toolId(), req.recipeId(), req.limit())
				.stream().map(KnowledgeLite::of).toList());
	}

	@PutMapping("/knowledge/{id}/embedding")
	public ApiResponse<Map<String, Object>> setKnowledgeEmbedding(@PathVariable Long id,
	                                                               @RequestBody Map<String, String> body) {
		return ApiResponse.ok(service.setKnowledgeEmbedding(id, body.get("embedding")));
	}

	@PostMapping("/knowledge/{id}/use")
	public ApiResponse<Map<String, Object>> bumpKnowledgeUse(@PathVariable Long id) {
		return ApiResponse.ok(service.bumpKnowledgeUse(id));
	}

	@GetMapping("/knowledge/missing-embeddings")
	public ApiResponse<List<KnowledgeLite>> missingKnowledgeEmbeddings(
			@RequestParam(value = "limit", defaultValue = "20") int limit) {
		return ApiResponse.ok(service.missingKnowledgeEmbeddings(limit)
				.stream().map(KnowledgeLite::of).toList());
	}

	@GetMapping("/knowledge/high-priority")
	public ApiResponse<List<KnowledgeLite>> highPriorityKnowledge(
			@RequestParam(value = "user_id", defaultValue = "1") Long userId,
			@RequestParam(value = "limit", defaultValue = "20") int limit) {
		return ApiResponse.ok(service.highPriorityKnowledge(userId, limit)
				.stream().map(KnowledgeLite::of).toList());
	}

	// ── Examples (few-shot) ───────────────────────────────────────────────

	@PostMapping("/examples/search")
	public ApiResponse<List<ExampleLite>> searchExamples(@RequestBody ExampleSearchRequest req) {
		return ApiResponse.ok(service.searchExamples(req.userId(), req.queryVec(),
				req.skillSlug(), req.toolId(), req.recipeId(), req.limit())
				.stream().map(ExampleLite::of).toList());
	}

	@PutMapping("/examples/{id}/embedding")
	public ApiResponse<Map<String, Object>> setExampleEmbedding(@PathVariable Long id,
	                                                             @RequestBody Map<String, String> body) {
		return ApiResponse.ok(service.setExampleEmbedding(id, body.get("embedding")));
	}

	@GetMapping("/examples/missing-embeddings")
	public ApiResponse<List<ExampleLite>> missingExampleEmbeddings(
			@RequestParam(value = "limit", defaultValue = "20") int limit) {
		return ApiResponse.ok(service.missingExampleEmbeddings(limit)
				.stream().map(ExampleLite::of).toList());
	}

	// ── Lite DTOs (slim wire shape) ───────────────────────────────────────

	public record DirectiveLite(Long id, String scopeType, String scopeValue,
	                             String title, String body, String priority) {
		static DirectiveLite of(AgentDirectiveEntity e) {
			return new DirectiveLite(e.getId(), e.getScopeType(), e.getScopeValue(),
					e.getTitle(), e.getBody(), e.getPriority());
		}
	}

	public record LexiconLite(Long id, String term, String standard, String note) {
		static LexiconLite of(AgentLexiconEntity e) {
			return new LexiconLite(e.getId(), e.getTerm(), e.getStandard(), e.getNote());
		}
	}

	public record KnowledgeLite(Long id, String scopeType, String scopeValue,
	                             String title, String body, String priority) {
		static KnowledgeLite of(AgentKnowledgeEntity e) {
			return new KnowledgeLite(e.getId(), e.getScopeType(), e.getScopeValue(),
					e.getTitle(), e.getBody(), e.getPriority());
		}
	}

	public record ExampleLite(Long id, String scopeType, String scopeValue,
	                          String title, String inputText, String outputText) {
		static ExampleLite of(AgentExampleEntity e) {
			return new ExampleLite(e.getId(), e.getScopeType(), e.getScopeValue(),
					e.getTitle(), e.getInputText(), e.getOutputText());
		}
	}

	public record KnowledgeSearchRequest(
			Long userId, String queryVec,
			String skillSlug, String toolId, String recipeId, Integer limit) {}

	public record ExampleSearchRequest(
			Long userId, String queryVec,
			String skillSlug, String toolId, String recipeId, Integer limit) {}
}
