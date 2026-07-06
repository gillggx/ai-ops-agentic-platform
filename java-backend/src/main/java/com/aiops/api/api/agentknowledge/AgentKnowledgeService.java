package com.aiops.api.api.agentknowledge;

import com.aiops.api.api.memory.MemoryGovernancePolicy;
import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Role;
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
	private final BlockDocMemoRepository docMemoRepo;

	/** Builder's doc sticky-notes — read-only "Builder memory" for the
	 *  /agent-knowledge page. Newest first, capped. */
	@Transactional(readOnly = true)
	public List<Dtos.DocMemoDto> listDocMemos() {
		return docMemoRepo.findTop200ByOrderByIdDesc()
				.stream().map(Dtos.DocMemoDto::of).toList();
	}

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
		e.setWrittenBy("human");   // V71: manual UI create is human-authored
		// V75 governance: ON_DUTY-only callers create DRAFTS (invisible to
		// retrieval) — a PE / IT_ADMIN approves via approveKnowledge. Fail
		// closed: null / empty roles are treated as ON_DUTY.
		if (canPublishKnowledge(caller)) {
			e.setStatus("active");
		} else {
			e.setStatus("draft");
			e.setActive(false);
		}
		backfillReviewAt(e);   // W3: domain|procedure rows carry an annual review date
		// embedding will be filled in by sidecar's _backfill_embeddings (async)
		return Dtos.KnowledgeDto.of(knowledgeRepo.save(e));
	}

	/** V75 review queue — ALL users' drafts, cross-user by design: ON_DUTY
	 *  submits under their own user_id and a (different) PE / IT_ADMIN
	 *  reviews. The role gate IS the authorization here. */
	@Transactional(readOnly = true)
	public List<Dtos.KnowledgeDto> listDrafts(AuthPrincipal caller) {
		requireReviewerRole(caller);
		return knowledgeRepo.findByStatusOrderByCreatedAtDesc("draft")
				.stream().map(Dtos.KnowledgeDto::of).toList();
	}

	/** V75 approve path: draft → active. This is the ONLY way a draft goes
	 *  live — the PATCH active toggle refuses drafts (see patchKnowledge).
	 *  Cross-user on purpose (no owner check): the reviewing PE / IT_ADMIN is
	 *  not the ON_DUTY submitter — the role gate IS the authorization. */
	@Transactional
	public Dtos.KnowledgeDto approveKnowledge(Long id, AuthPrincipal caller) {
		requireReviewerRole(caller);
		AgentKnowledgeEntity e = knowledgeRepo.findById(id)
				.orElseThrow(() -> ApiException.notFound("knowledge"));
		if (!"draft".equals(e.getStatus())) {
			throw ApiException.badRequest(
					"knowledge " + id + " is '" + e.getStatus() + "' — only drafts can be approved");
		}
		e.setStatus("active");
		e.setActive(true);
		backfillReviewAt(e);   // W3: agent-written domain|procedure drafts get a review date on approval
		e.setUpdatedAt(OffsetDateTime.now());
		return Dtos.KnowledgeDto.of(e);
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
		if (req.active() != null)   applyActiveToggle(e, req.active());
		e.setUpdatedAt(OffsetDateTime.now());
		// Invalidation goes through native SQL — the `embedding` column is
		// JPA-readonly (insertable/updatable=false) because Hibernate binds
		// String as VARCHAR and pgvector refuses the implicit cast. Sidecar's
		// _backfill_embeddings will re-embed on next pass.
		if (bodyChanged) knowledgeRepo.clearEmbedding(id);
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
		e.setUpdatedAt(OffsetDateTime.now());
		// See patchKnowledge — same pgvector ↔ JPA write-path workaround.
		if (inputChanged) exampleRepo.clearEmbedding(id);
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
	// V75 lifecycle helpers
	// ══════════════════════════════════════════════════════════════════════

	/** PE / IT_ADMIN publish directly; anyone else (ON_DUTY, or no roles at
	 *  all — fail closed) only produces drafts. */
	private static boolean canPublishKnowledge(AuthPrincipal caller) {
		return caller.roles() != null
				&& (caller.roles().contains(Role.PE) || caller.roles().contains(Role.IT_ADMIN));
	}

	/** Review-flow gate (listDrafts / approveKnowledge): same PE / IT_ADMIN
	 *  authority as publishing — defense-in-depth behind the controller's
	 *  ADMIN_OR_PE @PreAuthorize, and fail-closed on null / empty roles. */
	private static void requireReviewerRole(AuthPrincipal caller) {
		if (!canPublishKnowledge(caller)) {
			throw ApiException.forbidden("PE or IT_ADMIN role required to review knowledge drafts");
		}
	}

	/** W3 governance: durable classes (domain | procedure) carry an annual
	 *  review date. Backfilled on create AND on draft approval, only when the
	 *  caller didn't already set one — never overwrites an explicit review_at.
	 *  Window lives in {@link MemoryGovernancePolicy#REVIEW_PERIOD_DAYS}
	 *  (sidecar mirrors the constant — see that class's sync-duty note). */
	private static void backfillReviewAt(AgentKnowledgeEntity e) {
		if (e.getReviewAt() == null && MemoryGovernancePolicy.requiresReview(e.getMemoClass())) {
			e.setReviewAt(MemoryGovernancePolicy.nextReviewAt(OffsetDateTime.now()));
		}
	}

	/** Keep the V75 {@code status} column coherent with the legacy
	 *  {@code active} toggle:
	 *  <ul>
	 *    <li>disable → status 'archived' ONLY if currently 'active'
	 *        (draft/stale keep their lifecycle state);</li>
	 *    <li>enable → status 'active', EXCEPT drafts: enabling a draft must go
	 *        through {@link #approveKnowledge} — the toggle refuses so a draft
	 *        can never silently go live.</li>
	 *  </ul> */
	private static void applyActiveToggle(AgentKnowledgeEntity e, boolean enable) {
		if (enable) {
			if ("draft".equals(e.getStatus())) {
				throw ApiException.badRequest(
						"knowledge " + e.getId() + " is a draft — use the approve endpoint, not the active toggle");
			}
			e.setActive(true);
			e.setStatus("active");
		} else {
			e.setActive(false);
			if ("active".equals(e.getStatus())) {
				e.setStatus("archived");
			}
		}
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
