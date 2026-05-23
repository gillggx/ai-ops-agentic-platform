package com.aiops.api.api.agentknowledge;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 2026-05-11: User-owned Agent Rules &amp; Knowledge surface
 * (Phase 1 + 2). Combined controller for the 4 resources to keep the file
 * count down — endpoints are namespace-distinct anyway.
 *
 * <p>2026-05-23 (Phase 12 OOP refactor): controller is now a thin HTTP
 * layer; validation / ownership / entity construction / embedding
 * invalidation moved to {@link AgentKnowledgeService}.
 *
 * <p>Naming chose "directives" over "rules" to avoid clashing with the
 * existing /api/v1/rules (UserRulesController) which wraps auto_patrols.
 */
@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class AgentKnowledgeController {

	private final AgentKnowledgeService service;

	// ── Directives ────────────────────────────────────────────────────────

	@GetMapping("/agent-directives")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<Dtos.DirectiveDto>> listDirectives(@AuthenticationPrincipal AuthPrincipal caller) {
		return ApiResponse.ok(service.listDirectives(caller));
	}

	@PostMapping("/agent-directives")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Dtos.DirectiveDto> createDirective(@RequestBody Dtos.CreateDirectiveRequest req,
	                                                       @AuthenticationPrincipal AuthPrincipal caller) {
		return ApiResponse.ok(service.createDirective(req, caller));
	}

	@PatchMapping("/agent-directives/{id}")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Dtos.DirectiveDto> patchDirective(@PathVariable Long id,
	                                                      @RequestBody Dtos.PatchDirectiveRequest req,
	                                                      @AuthenticationPrincipal AuthPrincipal caller) {
		return ApiResponse.ok(service.patchDirective(id, req, caller));
	}

	@DeleteMapping("/agent-directives/{id}")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Void> deleteDirective(@PathVariable Long id, @AuthenticationPrincipal AuthPrincipal caller) {
		service.deleteDirective(id, caller);
		return ApiResponse.ok(null);
	}

	@GetMapping("/agent-directives/{id}/fires")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<Dtos.FireDto>> directiveFires(@PathVariable Long id,
	                                                       @AuthenticationPrincipal AuthPrincipal caller) {
		return ApiResponse.ok(service.directiveFires(id, caller));
	}

	// ── Lexicon ───────────────────────────────────────────────────────────

	@GetMapping("/agent-lexicon")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<Dtos.LexiconDto>> listLexicon(@AuthenticationPrincipal AuthPrincipal caller) {
		return ApiResponse.ok(service.listLexicon(caller));
	}

	@PostMapping("/agent-lexicon")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Dtos.LexiconDto> createLexicon(@RequestBody Dtos.CreateLexiconRequest req,
	                                                   @AuthenticationPrincipal AuthPrincipal caller) {
		return ApiResponse.ok(service.createLexicon(req, caller));
	}

	@PatchMapping("/agent-lexicon/{id}")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Dtos.LexiconDto> patchLexicon(@PathVariable Long id,
	                                                  @RequestBody Dtos.PatchLexiconRequest req,
	                                                  @AuthenticationPrincipal AuthPrincipal caller) {
		return ApiResponse.ok(service.patchLexicon(id, req, caller));
	}

	@DeleteMapping("/agent-lexicon/{id}")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Void> deleteLexicon(@PathVariable Long id, @AuthenticationPrincipal AuthPrincipal caller) {
		service.deleteLexicon(id, caller);
		return ApiResponse.ok(null);
	}

	// ── Knowledge ─────────────────────────────────────────────────────────

	@GetMapping("/agent-knowledge")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<Dtos.KnowledgeDto>> listKnowledge(@AuthenticationPrincipal AuthPrincipal caller) {
		return ApiResponse.ok(service.listKnowledge(caller));
	}

	@PostMapping("/agent-knowledge")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Dtos.KnowledgeDto> createKnowledge(@RequestBody Dtos.CreateKnowledgeRequest req,
	                                                       @AuthenticationPrincipal AuthPrincipal caller) {
		return ApiResponse.ok(service.createKnowledge(req, caller));
	}

	@PatchMapping("/agent-knowledge/{id}")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Dtos.KnowledgeDto> patchKnowledge(@PathVariable Long id,
	                                                      @RequestBody Dtos.PatchKnowledgeRequest req,
	                                                      @AuthenticationPrincipal AuthPrincipal caller) {
		return ApiResponse.ok(service.patchKnowledge(id, req, caller));
	}

	@DeleteMapping("/agent-knowledge/{id}")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Void> deleteKnowledge(@PathVariable Long id, @AuthenticationPrincipal AuthPrincipal caller) {
		service.deleteKnowledge(id, caller);
		return ApiResponse.ok(null);
	}

	// ── Examples ──────────────────────────────────────────────────────────

	@GetMapping("/agent-examples")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<Dtos.ExampleDto>> listExamples(@AuthenticationPrincipal AuthPrincipal caller) {
		return ApiResponse.ok(service.listExamples(caller));
	}

	@PostMapping("/agent-examples")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Dtos.ExampleDto> createExample(@RequestBody Dtos.CreateExampleRequest req,
	                                                   @AuthenticationPrincipal AuthPrincipal caller) {
		return ApiResponse.ok(service.createExample(req, caller));
	}

	@PatchMapping("/agent-examples/{id}")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Dtos.ExampleDto> patchExample(@PathVariable Long id,
	                                                  @RequestBody Dtos.PatchExampleRequest req,
	                                                  @AuthenticationPrincipal AuthPrincipal caller) {
		return ApiResponse.ok(service.patchExample(id, req, caller));
	}

	@DeleteMapping("/agent-examples/{id}")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Void> deleteExample(@PathVariable Long id, @AuthenticationPrincipal AuthPrincipal caller) {
		service.deleteExample(id, caller);
		return ApiResponse.ok(null);
	}
}
