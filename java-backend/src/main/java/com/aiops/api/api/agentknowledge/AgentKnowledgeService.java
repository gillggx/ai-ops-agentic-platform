package com.aiops.api.api.agentknowledge;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.common.ApiException;
import com.aiops.api.domain.agentknowledge.*;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Set;

/**
 * User-owned Agent Rules & Knowledge business logic — directives, lexicon,
 * knowledge, examples.
 *
 * <p>Extracted from {@code AgentKnowledgeController} 2026-05-23 as part of
 * the Phase 12 OOP refactor. Controller now binds HTTP concerns; this
 * service owns scope/priority validation, owner-of-record check, entity
 * construction, and embedding invalidation on body/input change.
 *
 * <p>Single service covering 4 resources because they share the same
 * userId-ownership + scope + priority model — splitting them into 4
 * separate beans would duplicate the validators without buying isolation.
 * Sections below mirror the resource boundary so the file stays scannable.
 */
@Service
@RequiredArgsConstructor
public class AgentKnowledgeService {

	static final Set<String> SCOPE_TYPES = Set.of("global", "skill", "tool", "recipe");
	static final Set<String> PRIORITIES = Set.of("high", "med", "low");

	private final AgentDirectiveRepository directiveRepo;
	private final AgentDirectiveFireRepository fireRepo;
	private final AgentLexiconRepository lexiconRepo;
	private final AgentKnowledgeRepository knowledgeRepo;
	private final AgentExampleRepository exampleRepo;

	// ══════════════════════════════════════════════════════════════════════
	// Directives
	// ══════════════════════════════════════════════════════════════════════

	public List<Dtos.DirectiveDto> listDirectives(AuthPrincipal caller) {
		return directiveRepo.findByUserIdOrderByCreatedAtDesc(caller.userId())
				.stream()
				.map(e -> Dtos.DirectiveDto.of(e, fireRepo.countByDirectiveId(e.getId())))
				.toList();
	}

	@Transactional
	public Dtos.DirectiveDto createDirective(Dtos.CreateDirectiveRequest req, AuthPrincipal caller) {
		validateScope(req.scopeType(), req.scopeValue());
		validatePriority(req.priority());
		requireText("title", req.title());
		requireText("body", req.body());
		AgentDirectiveEntity e = new AgentDirectiveEntity();
		e.setUserId(caller.userId());
		e.setScopeType(req.scopeType());
		e.setScopeValue("global".equals(req.scopeType()) ? null : req.scopeValue());
		e.setTitle(req.title());
		e.setBody(req.body());
		e.setPriority(req.priority() != null ? req.priority() : "med");
		return Dtos.DirectiveDto.of(directiveRepo.save(e), 0);
	}

	@Transactional
	public Dtos.DirectiveDto patchDirective(Long id, Dtos.PatchDirectiveRequest req, AuthPrincipal caller) {
		AgentDirectiveEntity e = directiveRepo.findById(id)
				.orElseThrow(() -> ApiException.notFound("directive"));
		ensureOwner(e.getUserId(), caller);
		if (req.scopeType() != null) {
			validateScope(req.scopeType(), req.scopeValue());
			e.setScopeType(req.scopeType());
			e.setScopeValue("global".equals(req.scopeType()) ? null : req.scopeValue());
		}
		if (req.title() != null)    e.setTitle(req.title());
		if (req.body() != null)     e.setBody(req.body());
		if (req.priority() != null) { validatePriority(req.priority()); e.setPriority(req.priority()); }
		if (req.active() != null)   e.setActive(req.active());
		e.setUpdatedAt(OffsetDateTime.now());
		return Dtos.DirectiveDto.of(e, fireRepo.countByDirectiveId(e.getId()));
	}

	@Transactional
	public void deleteDirective(Long id, AuthPrincipal caller) {
		AgentDirectiveEntity e = directiveRepo.findById(id)
				.orElseThrow(() -> ApiException.notFound("directive"));
		ensureOwner(e.getUserId(), caller);
		directiveRepo.deleteById(id);
	}

	public List<Dtos.FireDto> directiveFires(Long id, AuthPrincipal caller) {
		AgentDirectiveEntity e = directiveRepo.findById(id)
				.orElseThrow(() -> ApiException.notFound("directive"));
		ensureOwner(e.getUserId(), caller);
		return fireRepo.findByDirectiveIdOrderByFiredAtDesc(id, PageRequest.of(0, 20))
				.stream().map(Dtos.FireDto::of).toList();
	}

	// ══════════════════════════════════════════════════════════════════════
	// Lexicon
	// ══════════════════════════════════════════════════════════════════════

	public List<Dtos.LexiconDto> listLexicon(AuthPrincipal caller) {
		return lexiconRepo.findByUserIdOrderByUsesDescTermAsc(caller.userId())
				.stream().map(Dtos.LexiconDto::of).toList();
	}

	@Transactional
	public Dtos.LexiconDto createLexicon(Dtos.CreateLexiconRequest req, AuthPrincipal caller) {
		requireText("term", req.term());
		requireText("standard", req.standard());
		AgentLexiconEntity e = new AgentLexiconEntity();
		e.setUserId(caller.userId());
		e.setTerm(req.term().trim());
		e.setStandard(req.standard().trim());
		e.setNote(req.note());
		return Dtos.LexiconDto.of(lexiconRepo.save(e));
	}

	@Transactional
	public Dtos.LexiconDto patchLexicon(Long id, Dtos.PatchLexiconRequest req, AuthPrincipal caller) {
		AgentLexiconEntity e = lexiconRepo.findById(id)
				.orElseThrow(() -> ApiException.notFound("lexicon"));
		ensureOwner(e.getUserId(), caller);
		if (req.term() != null)     e.setTerm(req.term().trim());
		if (req.standard() != null) e.setStandard(req.standard().trim());
		if (req.note() != null)     e.setNote(req.note());
		e.setUpdatedAt(OffsetDateTime.now());
		return Dtos.LexiconDto.of(e);
	}

	@Transactional
	public void deleteLexicon(Long id, AuthPrincipal caller) {
		AgentLexiconEntity e = lexiconRepo.findById(id)
				.orElseThrow(() -> ApiException.notFound("lexicon"));
		ensureOwner(e.getUserId(), caller);
		lexiconRepo.deleteById(id);
	}

	// ══════════════════════════════════════════════════════════════════════
	// Knowledge
	// ══════════════════════════════════════════════════════════════════════

	public List<Dtos.KnowledgeDto> listKnowledge(AuthPrincipal caller) {
		return knowledgeRepo.findByUserIdOrderByCreatedAtDesc(caller.userId())
				.stream().map(Dtos.KnowledgeDto::of).toList();
	}

	@Transactional
	public Dtos.KnowledgeDto createKnowledge(Dtos.CreateKnowledgeRequest req, AuthPrincipal caller) {
		validateScope(req.scopeType(), req.scopeValue());
		validatePriority(req.priority());
		requireText("title", req.title());
		requireText("body", req.body());
		AgentKnowledgeEntity e = new AgentKnowledgeEntity();
		e.setUserId(caller.userId());
		e.setScopeType(req.scopeType());
		e.setScopeValue("global".equals(req.scopeType()) ? null : req.scopeValue());
		e.setTitle(req.title());
		e.setBody(req.body());
		e.setPriority(req.priority() != null ? req.priority() : "med");
		// embedding will be filled in by sidecar's _backfill_embeddings (async)
		return Dtos.KnowledgeDto.of(knowledgeRepo.save(e));
	}

	@Transactional
	public Dtos.KnowledgeDto patchKnowledge(Long id, Dtos.PatchKnowledgeRequest req, AuthPrincipal caller) {
		AgentKnowledgeEntity e = knowledgeRepo.findById(id)
				.orElseThrow(() -> ApiException.notFound("knowledge"));
		ensureOwner(e.getUserId(), caller);
		boolean bodyChanged = false;
		if (req.scopeType() != null) {
			validateScope(req.scopeType(), req.scopeValue());
			e.setScopeType(req.scopeType());
			e.setScopeValue("global".equals(req.scopeType()) ? null : req.scopeValue());
		}
		if (req.title() != null)    e.setTitle(req.title());
		if (req.body() != null)     { e.setBody(req.body()); bodyChanged = true; }
		if (req.priority() != null) { validatePriority(req.priority()); e.setPriority(req.priority()); }
		if (req.active() != null)   e.setActive(req.active());
		if (bodyChanged) e.setEmbedding(null);  // invalidate; sidecar re-embeds
		e.setUpdatedAt(OffsetDateTime.now());
		return Dtos.KnowledgeDto.of(e);
	}

	@Transactional
	public void deleteKnowledge(Long id, AuthPrincipal caller) {
		AgentKnowledgeEntity e = knowledgeRepo.findById(id)
				.orElseThrow(() -> ApiException.notFound("knowledge"));
		ensureOwner(e.getUserId(), caller);
		knowledgeRepo.deleteById(id);
	}

	// ══════════════════════════════════════════════════════════════════════
	// Examples
	// ══════════════════════════════════════════════════════════════════════

	public List<Dtos.ExampleDto> listExamples(AuthPrincipal caller) {
		return exampleRepo.findByUserIdOrderByCreatedAtDesc(caller.userId())
				.stream().map(Dtos.ExampleDto::of).toList();
	}

	@Transactional
	public Dtos.ExampleDto createExample(Dtos.CreateExampleRequest req, AuthPrincipal caller) {
		validateScope(req.scopeType(), req.scopeValue());
		requireText("title", req.title());
		requireText("input_text", req.inputText());
		requireText("output_text", req.outputText());
		AgentExampleEntity e = new AgentExampleEntity();
		e.setUserId(caller.userId());
		e.setScopeType(req.scopeType());
		e.setScopeValue("global".equals(req.scopeType()) ? null : req.scopeValue());
		e.setTitle(req.title());
		e.setInputText(req.inputText());
		e.setOutputText(req.outputText());
		return Dtos.ExampleDto.of(exampleRepo.save(e));
	}

	@Transactional
	public Dtos.ExampleDto patchExample(Long id, Dtos.PatchExampleRequest req, AuthPrincipal caller) {
		AgentExampleEntity e = exampleRepo.findById(id)
				.orElseThrow(() -> ApiException.notFound("example"));
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
		return Dtos.ExampleDto.of(e);
	}

	@Transactional
	public void deleteExample(Long id, AuthPrincipal caller) {
		AgentExampleEntity e = exampleRepo.findById(id)
				.orElseThrow(() -> ApiException.notFound("example"));
		ensureOwner(e.getUserId(), caller);
		exampleRepo.deleteById(id);
	}

	// ══════════════════════════════════════════════════════════════════════
	// Shared validators
	// ══════════════════════════════════════════════════════════════════════

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

	private static void requireText(String field, String value) {
		if (value == null || value.isBlank()) {
			throw ApiException.badRequest(field + " required");
		}
	}
}
