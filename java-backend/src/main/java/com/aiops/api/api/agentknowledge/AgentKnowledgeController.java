package com.aiops.api.api.agentknowledge;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.agentknowledge.*;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.PageRequest;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Set;

/**
 * 2026-05-11: User-owned Agent Rules &amp; Knowledge surface
 * (Phase 1 + 2). Combined controller for the 4 resources to keep the file
 * count down — endpoints are namespace-distinct anyway.
 *
 * <p>Naming chose "directives" over "rules" to avoid clashing with the
 * existing /api/v1/rules (UserRulesController) which wraps auto_patrols.
 */
@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class AgentKnowledgeController {

    private static final Set<String> SCOPE_TYPES = Set.of("global", "skill", "tool", "recipe");
    private static final Set<String> PRIORITIES  = Set.of("high", "med", "low");

    private final AgentDirectiveRepository directiveRepo;
    private final AgentDirectiveFireRepository fireRepo;
    private final AgentLexiconRepository lexiconRepo;
    private final AgentKnowledgeRepository knowledgeRepo;
    private final AgentExampleRepository exampleRepo;

    // ── Directives ────────────────────────────────────────────────────

    @GetMapping("/agent-directives")
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<List<Dtos.DirectiveDto>> listDirectives(@AuthenticationPrincipal AuthPrincipal caller) {
        List<AgentDirectiveEntity> rows = directiveRepo.findByUserIdOrderByCreatedAtDesc(caller.userId());
        return ApiResponse.ok(rows.stream()
                .map(e -> Dtos.DirectiveDto.of(e, fireRepo.countByDirectiveId(e.getId())))
                .toList());
    }

    @PostMapping("/agent-directives")
    @Transactional
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<Dtos.DirectiveDto> createDirective(
            @RequestBody Dtos.CreateDirectiveRequest req,
            @AuthenticationPrincipal AuthPrincipal caller) {
        validateScope(req.scopeType(), req.scopeValue());
        validatePriority(req.priority());
        if (req.title() == null || req.title().isBlank()) throw ApiException.badRequest("title required");
        if (req.body()  == null || req.body().isBlank())  throw ApiException.badRequest("body required");
        AgentDirectiveEntity e = new AgentDirectiveEntity();
        e.setUserId(caller.userId());
        e.setScopeType(req.scopeType());
        e.setScopeValue("global".equals(req.scopeType()) ? null : req.scopeValue());
        e.setTitle(req.title());
        e.setBody(req.body());
        e.setPriority(req.priority() != null ? req.priority() : "med");
        AgentDirectiveEntity saved = directiveRepo.save(e);
        return ApiResponse.ok(Dtos.DirectiveDto.of(saved, 0));
    }

    @PatchMapping("/agent-directives/{id}")
    @Transactional
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<Dtos.DirectiveDto> patchDirective(
            @PathVariable Long id,
            @RequestBody Dtos.PatchDirectiveRequest req,
            @AuthenticationPrincipal AuthPrincipal caller) {
        AgentDirectiveEntity e = directiveRepo.findById(id).orElseThrow(() -> ApiException.notFound("directive"));
        ensureOwner(e.getUserId(), caller);
        if (req.scopeType() != null) {
            validateScope(req.scopeType(), req.scopeValue());
            e.setScopeType(req.scopeType());
            e.setScopeValue("global".equals(req.scopeType()) ? null : req.scopeValue());
        }
        if (req.title() != null)    e.setTitle(req.title());
        if (req.body()  != null)    e.setBody(req.body());
        if (req.priority() != null) { validatePriority(req.priority()); e.setPriority(req.priority()); }
        if (req.active() != null)   e.setActive(req.active());
        e.setUpdatedAt(OffsetDateTime.now());
        return ApiResponse.ok(Dtos.DirectiveDto.of(e, fireRepo.countByDirectiveId(e.getId())));
    }

    @DeleteMapping("/agent-directives/{id}")
    @Transactional
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<Void> deleteDirective(@PathVariable Long id, @AuthenticationPrincipal AuthPrincipal caller) {
        AgentDirectiveEntity e = directiveRepo.findById(id).orElseThrow(() -> ApiException.notFound("directive"));
        ensureOwner(e.getUserId(), caller);
        directiveRepo.deleteById(id);
        return ApiResponse.ok(null);
    }

    @GetMapping("/agent-directives/{id}/fires")
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<List<Dtos.FireDto>> directiveFires(
            @PathVariable Long id,
            @AuthenticationPrincipal AuthPrincipal caller) {
        AgentDirectiveEntity e = directiveRepo.findById(id).orElseThrow(() -> ApiException.notFound("directive"));
        ensureOwner(e.getUserId(), caller);
        var page = fireRepo.findByDirectiveIdOrderByFiredAtDesc(id, PageRequest.of(0, 20));
        return ApiResponse.ok(page.stream().map(Dtos.FireDto::of).toList());
    }

    // ── Lexicon ───────────────────────────────────────────────────────

    @GetMapping("/agent-lexicon")
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<List<Dtos.LexiconDto>> listLexicon(@AuthenticationPrincipal AuthPrincipal caller) {
        return ApiResponse.ok(lexiconRepo.findByUserIdOrderByUsesDescTermAsc(caller.userId())
                .stream().map(Dtos.LexiconDto::of).toList());
    }

    @PostMapping("/agent-lexicon")
    @Transactional
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<Dtos.LexiconDto> createLexicon(
            @RequestBody Dtos.CreateLexiconRequest req,
            @AuthenticationPrincipal AuthPrincipal caller) {
        if (req.term() == null || req.term().isBlank()) throw ApiException.badRequest("term required");
        if (req.standard() == null || req.standard().isBlank()) throw ApiException.badRequest("standard required");
        AgentLexiconEntity e = new AgentLexiconEntity();
        e.setUserId(caller.userId());
        e.setTerm(req.term().trim());
        e.setStandard(req.standard().trim());
        e.setNote(req.note());
        return ApiResponse.ok(Dtos.LexiconDto.of(lexiconRepo.save(e)));
    }

    @PatchMapping("/agent-lexicon/{id}")
    @Transactional
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<Dtos.LexiconDto> patchLexicon(
            @PathVariable Long id,
            @RequestBody Dtos.PatchLexiconRequest req,
            @AuthenticationPrincipal AuthPrincipal caller) {
        AgentLexiconEntity e = lexiconRepo.findById(id).orElseThrow(() -> ApiException.notFound("lexicon"));
        ensureOwner(e.getUserId(), caller);
        if (req.term() != null)     e.setTerm(req.term().trim());
        if (req.standard() != null) e.setStandard(req.standard().trim());
        if (req.note() != null)     e.setNote(req.note());
        e.setUpdatedAt(OffsetDateTime.now());
        return ApiResponse.ok(Dtos.LexiconDto.of(e));
    }

    @DeleteMapping("/agent-lexicon/{id}")
    @Transactional
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<Void> deleteLexicon(@PathVariable Long id, @AuthenticationPrincipal AuthPrincipal caller) {
        AgentLexiconEntity e = lexiconRepo.findById(id).orElseThrow(() -> ApiException.notFound("lexicon"));
        ensureOwner(e.getUserId(), caller);
        lexiconRepo.deleteById(id);
        return ApiResponse.ok(null);
    }

    // ── Knowledge ─────────────────────────────────────────────────────

    @GetMapping("/agent-knowledge")
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<List<Dtos.KnowledgeDto>> listKnowledge(@AuthenticationPrincipal AuthPrincipal caller) {
        return ApiResponse.ok(knowledgeRepo.findByUserIdOrderByCreatedAtDesc(caller.userId())
                .stream().map(Dtos.KnowledgeDto::of).toList());
    }

    @PostMapping("/agent-knowledge")
    @Transactional
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<Dtos.KnowledgeDto> createKnowledge(
            @RequestBody Dtos.CreateKnowledgeRequest req,
            @AuthenticationPrincipal AuthPrincipal caller) {
        validateScope(req.scopeType(), req.scopeValue());
        validatePriority(req.priority());
        if (req.title() == null || req.title().isBlank()) throw ApiException.badRequest("title required");
        if (req.body()  == null || req.body().isBlank())  throw ApiException.badRequest("body required");
        AgentKnowledgeEntity e = new AgentKnowledgeEntity();
        e.setUserId(caller.userId());
        e.setScopeType(req.scopeType());
        e.setScopeValue("global".equals(req.scopeType()) ? null : req.scopeValue());
        e.setTitle(req.title());
        e.setBody(req.body());
        e.setPriority(req.priority() != null ? req.priority() : "med");
        // embedding will be filled in by sidecar's _backfill_embeddings (async)
        return ApiResponse.ok(Dtos.KnowledgeDto.of(knowledgeRepo.save(e)));
    }

    @PatchMapping("/agent-knowledge/{id}")
    @Transactional
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<Dtos.KnowledgeDto> patchKnowledge(
            @PathVariable Long id,
            @RequestBody Dtos.PatchKnowledgeRequest req,
            @AuthenticationPrincipal AuthPrincipal caller) {
        AgentKnowledgeEntity e = knowledgeRepo.findById(id).orElseThrow(() -> ApiException.notFound("knowledge"));
        ensureOwner(e.getUserId(), caller);
        boolean bodyChanged = false;
        if (req.scopeType() != null) {
            validateScope(req.scopeType(), req.scopeValue());
            e.setScopeType(req.scopeType());
            e.setScopeValue("global".equals(req.scopeType()) ? null : req.scopeValue());
        }
        if (req.title() != null)    e.setTitle(req.title());
        if (req.body()  != null)    { e.setBody(req.body()); bodyChanged = true; }
        if (req.priority() != null) { validatePriority(req.priority()); e.setPriority(req.priority()); }
        if (req.active() != null)   e.setActive(req.active());
        if (bodyChanged) e.setEmbedding(null);  // invalidate; sidecar re-embeds
        e.setUpdatedAt(OffsetDateTime.now());
        return ApiResponse.ok(Dtos.KnowledgeDto.of(e));
    }

    @DeleteMapping("/agent-knowledge/{id}")
    @Transactional
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<Void> deleteKnowledge(@PathVariable Long id, @AuthenticationPrincipal AuthPrincipal caller) {
        AgentKnowledgeEntity e = knowledgeRepo.findById(id).orElseThrow(() -> ApiException.notFound("knowledge"));
        ensureOwner(e.getUserId(), caller);
        knowledgeRepo.deleteById(id);
        return ApiResponse.ok(null);
    }

    // ── Examples ──────────────────────────────────────────────────────

    @GetMapping("/agent-examples")
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<List<Dtos.ExampleDto>> listExamples(@AuthenticationPrincipal AuthPrincipal caller) {
        return ApiResponse.ok(exampleRepo.findByUserIdOrderByCreatedAtDesc(caller.userId())
                .stream().map(Dtos.ExampleDto::of).toList());
    }

    @PostMapping("/agent-examples")
    @Transactional
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<Dtos.ExampleDto> createExample(
            @RequestBody Dtos.CreateExampleRequest req,
            @AuthenticationPrincipal AuthPrincipal caller) {
        validateScope(req.scopeType(), req.scopeValue());
        if (req.title() == null || req.title().isBlank()) throw ApiException.badRequest("title required");
        if (req.inputText()  == null || req.inputText().isBlank())  throw ApiException.badRequest("input_text required");
        if (req.outputText() == null || req.outputText().isBlank()) throw ApiException.badRequest("output_text required");
        AgentExampleEntity e = new AgentExampleEntity();
        e.setUserId(caller.userId());
        e.setScopeType(req.scopeType());
        e.setScopeValue("global".equals(req.scopeType()) ? null : req.scopeValue());
        e.setTitle(req.title());
        e.setInputText(req.inputText());
        e.setOutputText(req.outputText());
        return ApiResponse.ok(Dtos.ExampleDto.of(exampleRepo.save(e)));
    }

    @PatchMapping("/agent-examples/{id}")
    @Transactional
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<Dtos.ExampleDto> patchExample(
            @PathVariable Long id,
            @RequestBody Dtos.PatchExampleRequest req,
            @AuthenticationPrincipal AuthPrincipal caller) {
        AgentExampleEntity e = exampleRepo.findById(id).orElseThrow(() -> ApiException.notFound("example"));
        ensureOwner(e.getUserId(), caller);
        boolean inputChanged = false;
        if (req.scopeType() != null) {
            validateScope(req.scopeType(), req.scopeValue());
            e.setScopeType(req.scopeType());
            e.setScopeValue("global".equals(req.scopeType()) ? null : req.scopeValue());
        }
        if (req.title() != null)      e.setTitle(req.title());
        if (req.inputText() != null)  { e.setInputText(req.inputText()); inputChanged = true; }
        if (req.outputText() != null) e.setOutputText(req.outputText());
        if (inputChanged) e.setEmbedding(null);
        e.setUpdatedAt(OffsetDateTime.now());
        return ApiResponse.ok(Dtos.ExampleDto.of(e));
    }

    @DeleteMapping("/agent-examples/{id}")
    @Transactional
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<Void> deleteExample(@PathVariable Long id, @AuthenticationPrincipal AuthPrincipal caller) {
        AgentExampleEntity e = exampleRepo.findById(id).orElseThrow(() -> ApiException.notFound("example"));
        ensureOwner(e.getUserId(), caller);
        exampleRepo.deleteById(id);
        return ApiResponse.ok(null);
    }

    // ── Helpers ───────────────────────────────────────────────────────

    private static void validateScope(String type, String value) {
        if (type == null || !SCOPE_TYPES.contains(type)) {
            throw ApiException.badRequest("scope_type must be one of " + SCOPE_TYPES);
        }
        if (!"global".equals(type) && (value == null || value.isBlank())) {
            throw ApiException.badRequest("scope_value required when scope_type != global");
        }
    }

    private static void validatePriority(String p) {
        if (p != null && !PRIORITIES.contains(p)) {
            throw ApiException.badRequest("priority must be one of " + PRIORITIES);
        }
    }

    private static void ensureOwner(Long ownerId, AuthPrincipal caller) {
        if (!ownerId.equals(caller.userId())) {
            throw ApiException.forbidden("not your resource");
        }
    }
}
