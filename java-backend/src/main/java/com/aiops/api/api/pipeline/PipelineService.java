package com.aiops.api.api.pipeline;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.common.ApiException;
import com.aiops.api.domain.pipeline.PipelineAutoCheckTriggerEntity;
import com.aiops.api.domain.pipeline.PipelineAutoCheckTriggerRepository;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.pipeline.PipelineRunEntity;
import com.aiops.api.domain.pipeline.PipelineRunRepository;
import com.aiops.api.domain.pipeline.PublishedSkillEntity;
import com.aiops.api.domain.pipeline.PublishedSkillRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Pipeline business logic.
 *
 * <p>Extracted from {@link PipelineController} 2026-05-23 as part of the
 * Phase 12 Java OOP refactor. Controller stays HTTP-only (binding,
 * {@code @PreAuthorize}, DTO mapping); state machine, structural validation,
 * cross-entity writes (Pipeline + PublishedSkill + AutoCheckTrigger), and
 * JSON serdes live here.
 *
 * <p>Internally organised into three sections:
 * <ul>
 *   <li><b>CRUD</b> — list / get / create / update / delete / fork / listRuns</li>
 *   <li><b>Lifecycle</b> — transition / archive / publishDraftDoc / publish</li>
 *   <li><b>AutoCheck triggers</b> — publishAutoCheck / upsertAutoCheckTriggers /
 *       listAutoCheckTriggers (could become its own service if AutoCheck
 *       routing grows further)</li>
 * </ul>
 */
@Slf4j
@Service
public class PipelineService {

	/** 5-stage lifecycle: draft → validating → locked → active → archived.
	 *  Hard rule — kept here as a constant so it's testable and the controller
	 *  doesn't carry state-machine logic. */
	static final Map<String, Set<String>> ALLOWED_TRANSITIONS = Map.of(
			"draft",      Set.of("validating", "archived"),
			"validating", Set.of("locked", "draft"),
			"locked",     Set.of("active", "draft"),
			"active",     Set.of("archived"),
			"archived",   Set.of()
	);

	static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

	private final PipelineRepository repository;
	private final PublishedSkillRepository publishedSkillRepository;
	private final PipelineAutoCheckTriggerRepository autoCheckTriggerRepository;
	private final PipelineRunRepository pipelineRunRepository;
	private final PipelineDocGenerator docGenerator;
	private final ObjectMapper mapper;

	public PipelineService(PipelineRepository repository,
	                       PublishedSkillRepository publishedSkillRepository,
	                       PipelineAutoCheckTriggerRepository autoCheckTriggerRepository,
	                       PipelineRunRepository pipelineRunRepository,
	                       PipelineDocGenerator docGenerator,
	                       ObjectMapper mapper) {
		this.repository = repository;
		this.publishedSkillRepository = publishedSkillRepository;
		this.autoCheckTriggerRepository = autoCheckTriggerRepository;
		this.pipelineRunRepository = pipelineRunRepository;
		this.docGenerator = docGenerator;
		this.mapper = mapper;
	}

	// ══════════════════════════════════════════════════════════════════════
	// CRUD
	// ══════════════════════════════════════════════════════════════════════

	public List<PipelineEntity> list(String status) {
		if (status == null || status.isBlank()) return repository.findAll();
		return repository.findByStatus(status);
	}

	public PipelineEntity get(Long id) {
		return repository.findById(id).orElseThrow(() -> ApiException.notFound("pipeline"));
	}

	@Transactional
	public PipelineEntity create(PipelineDtos.CreateRequest req, AuthPrincipal caller) {
		if (req.pipelineJson() != null) checkStructural(req.pipelineJson());
		PipelineEntity e = new PipelineEntity();
		e.setName(req.name());
		if (req.description() != null) e.setDescription(req.description());
		if (req.pipelineKind() != null) e.setPipelineKind(req.pipelineKind());
		if (req.pipelineJson() != null) e.setPipelineJson(req.pipelineJson());
		if (req.version() != null) e.setVersion(req.version());
		e.setCreatedBy(caller.userId());
		return repository.save(e);
	}

	@Transactional
	public PipelineEntity update(Long id, PipelineDtos.UpdateRequest req) {
		PipelineEntity e = get(id);
		if ("locked".equalsIgnoreCase(e.getStatus()) || "archived".equalsIgnoreCase(e.getStatus())) {
			throw ApiException.conflict("pipeline is " + e.getStatus() + "; cannot mutate");
		}
		if (req.pipelineJson() != null) checkStructural(req.pipelineJson());
		if (req.name() != null) e.setName(req.name());
		if (req.description() != null) e.setDescription(req.description());
		if (req.pipelineKind() != null) e.setPipelineKind(req.pipelineKind());
		if (req.pipelineJson() != null) e.setPipelineJson(req.pipelineJson());
		if (req.autoDoc() != null) e.setAutoDoc(req.autoDoc());
		return repository.save(e);
	}

	@Transactional
	public void delete(Long id) {
		if (!repository.existsById(id)) throw ApiException.notFound("pipeline");
		repository.deleteById(id);
	}

	@Transactional
	public PipelineEntity fork(Long id, AuthPrincipal caller) {
		PipelineEntity src = get(id);
		// PR-B: clone allowed from any non-draft state (including archived, so users
		// can revive retired pipelines). Drafts are already editable in place.
		if ("draft".equals(src.getStatus())) {
			throw ApiException.conflict("Cannot clone a draft — just edit it directly");
		}

		Map<String, Object> payload = parsePipelineJson(src.getPipelineJson());
		Object metaRaw = payload.get("metadata");
		Map<String, Object> meta = (metaRaw instanceof Map<?, ?>)
				? new LinkedHashMap<>(asMap(metaRaw))
				: new LinkedHashMap<>();
		meta.put("fork_of", src.getId());
		meta.put("forked_at", OffsetDateTime.now().toString());
		payload.put("metadata", meta);

		PipelineEntity forked = new PipelineEntity();
		forked.setName(src.getName() + " (clone)");
		forked.setDescription(src.getDescription() == null ? "" : src.getDescription());
		forked.setStatus("draft");
		forked.setPipelineKind(src.getPipelineKind());
		forked.setVersion(src.getVersion());
		forked.setParentId(src.getId());
		forked.setCreatedBy(caller.userId());
		try {
			forked.setPipelineJson(mapper.writeValueAsString(payload));
		} catch (JsonProcessingException ex) {
			throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR,
					"serialize_failed", "Failed to serialize pipeline_json: " + ex.getMessage());
		}
		return repository.save(forked);
	}

	public List<PipelineRunEntity> listRuns(Long id, int limit) {
		int safe = Math.max(1, Math.min(limit, 200));
		List<PipelineRunEntity> all = pipelineRunRepository.findByPipelineIdOrderByStartedAtDesc(id);
		return all.subList(0, Math.min(all.size(), safe));
	}

	// ══════════════════════════════════════════════════════════════════════
	// Lifecycle
	// ══════════════════════════════════════════════════════════════════════

	@Transactional
	public PipelineEntity transition(Long id, String to) {
		PipelineEntity e = get(id);
		String from = e.getStatus();
		Set<String> allowed = ALLOWED_TRANSITIONS.getOrDefault(from, Set.of());
		if (!allowed.contains(to)) {
			throw ApiException.conflict("Cannot transition from '" + from + "' to '" + to
					+ "'. Allowed: " + allowed);
		}
		e.setStatus(to);
		OffsetDateTime now = OffsetDateTime.now();
		switch (to) {
			case "locked"   -> e.setLockedAt(now);
			case "active"   -> e.setPublishedAt(now);
			case "archived" -> e.setArchivedAt(now);
			case "draft"    -> { e.setLockedAt(null); e.setLockedBy(null); }
			default -> {}
		}
		return repository.save(e);
	}

	@Transactional
	public PipelineEntity archive(Long id) {
		PipelineEntity e = get(id);
		e.setStatus("archived");
		e.setArchivedAt(OffsetDateTime.now());
		return repository.save(e);
	}

	@Transactional
	public Map<String, Object> publishDraftDoc(Long id) {
		PipelineEntity e = get(id);
		// Allow draft-doc generation from validating OR locked (preview before locking).
		if (!"validating".equals(e.getStatus()) && !"locked".equals(e.getStatus())) {
			throw ApiException.conflict("Can only generate doc for validating/locked pipelines (got '"
					+ e.getStatus() + "')");
		}
		Map<String, Object> pipelineJson = parsePipelineJson(e.getPipelineJson());
		String kind = e.getPipelineKind() == null ? "diagnostic" : e.getPipelineKind();
		Map<String, Object> doc = docGenerator.generate(
				e.getId(), e.getName(), e.getVersion(), kind,
				e.getDescription() == null ? "" : e.getDescription(),
				pipelineJson);
		try {
			e.setAutoDoc(mapper.writeValueAsString(doc));
		} catch (JsonProcessingException ex) {
			throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR,
					"serialize_failed", "failed to serialize draft doc: " + ex.getMessage());
		}
		repository.save(e);
		return doc;
	}

	/** Promote a locked skill pipeline to active + create the PublishedSkill row.
	 *  Cross-entity write: PublishedSkill inserted first (FK reasons), then
	 *  Pipeline.status flipped to active. Both in the same {@code @Transactional}. */
	@Transactional
	public Map<String, Object> publish(Long id, PipelineDtos.PublishRequest req) {
		PipelineEntity e = get(id);
		if (!"locked".equals(e.getStatus())) {
			throw ApiException.conflict("Pipeline must be 'locked' before publish (got '"
					+ e.getStatus() + "')");
		}
		String kind = e.getPipelineKind();
		// Phase 5-UX-7: legacy "diagnostic" treated as "skill" for back-compat.
		if ("diagnostic".equals(kind)) kind = "skill";
		if (!"skill".equals(kind)) {
			throw ApiException.conflict("Only skill pipelines go to the Skill Registry. "
					+ "kind='" + e.getPipelineKind() + "' routes elsewhere: "
					+ "auto_patrol → /admin/auto-patrols binding, "
					+ "auto_check → /pipelines/{id}/publish-auto-check with event_types.");
		}

		Map<String, Object> doc = req.reviewedDoc();
		if (doc == null) throw ApiException.badRequest("reviewed_doc is required");
		List<String> missing = missingDocFields(doc);
		if (!missing.isEmpty()) {
			throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY,
					"missing_fields", "reviewed_doc missing fields: " + missing);
		}

		String slug = String.valueOf(doc.get("slug"));
		publishedSkillRepository.findBySlug(slug).ifPresent(existing -> {
			if ("active".equals(existing.getStatus())) {
				throw ApiException.conflict("slug '" + slug
						+ "' already exists — retire the old version or rename");
			}
		});

		PublishedSkillEntity skill = new PublishedSkillEntity();
		skill.setPipelineId(e.getId());
		skill.setPipelineVersion(e.getVersion());
		skill.setSlug(slug);
		Object docName = doc.get("name");
		skill.setName((docName instanceof String s && !s.isBlank()) ? s : e.getName());
		skill.setUseCase(stringOrEmpty(doc.get("use_case")));
		skill.setWhenToUse(jsonOr(doc.get("when_to_use"), "[]"));
		skill.setInputsSchema(jsonOr(doc.get("inputs_schema"), "[]"));
		skill.setOutputsSchema(jsonOr(doc.get("outputs_schema"), "{}"));
		Object example = doc.get("example_invocation");
		if (example != null) skill.setExampleInvocation(jsonOr(example, "null"));
		skill.setTags(jsonOr(doc.get("tags"), "[]"));
		skill.setStatus("active");
		skill.setPublishedBy(req.publishedBy() == null ? "admin" : req.publishedBy());
		publishedSkillRepository.save(skill);

		// Pipeline locked → active.
		e.setStatus("active");
		e.setPublishedAt(OffsetDateTime.now());
		repository.save(e);

		Map<String, Object> result = new LinkedHashMap<>();
		result.put("id", e.getId());
		result.put("name", e.getName());
		result.put("status", e.getStatus());
		result.put("pipeline_kind", e.getPipelineKind());
		result.put("version", e.getVersion());
		result.put("published_slug", slug);
		return result;
	}

	// ══════════════════════════════════════════════════════════════════════
	// AutoCheck triggers
	// ══════════════════════════════════════════════════════════════════════

	@Transactional
	public Map<String, Object> publishAutoCheck(Long id, PipelineDtos.PublishAutoCheckRequest req) {
		PipelineEntity e = get(id);
		if (!"locked".equals(e.getStatus())) {
			throw ApiException.conflict("Pipeline must be 'locked' before publish (got '"
					+ e.getStatus() + "')");
		}
		if (!"auto_check".equals(e.getPipelineKind())) {
			throw ApiException.conflict("publish-auto-check is only for pipeline_kind='auto_check' (got '"
					+ e.getPipelineKind() + "').");
		}
		List<EventTypeBinding> bindings = parseRequiredBindings(req.eventTypes());
		BindingReplaceResult replaceResult = replaceBindings(id, bindings);

		e.setStatus("active");
		e.setPublishedAt(OffsetDateTime.now());
		repository.save(e);

		Map<String, Object> result = new LinkedHashMap<>();
		result.put("id", e.getId());
		result.put("name", e.getName());
		result.put("status", e.getStatus());
		result.put("pipeline_kind", e.getPipelineKind());
		result.put("version", e.getVersion());
		result.put("event_types", new ArrayList<>(replaceResult.seen));
		result.put("bindings", replaceResult.bindings);
		return result;
	}

	/** P5: replace the auto_check binding set on an already-published pipeline.
	 *  Mirrors publishAutoCheck's binding-replace logic but skips the locked →
	 *  active transition (the pipeline is already active). Used by the canvas's
	 *  "編輯 Auto-Check 來源" button so users can change which alarms route to
	 *  a live pipeline without re-running the publish flow. */
	@Transactional
	public Map<String, Object> upsertAutoCheckTriggers(Long id, PipelineDtos.PublishAutoCheckRequest req) {
		PipelineEntity e = get(id);
		if (!"auto_check".equals(e.getPipelineKind())) {
			throw ApiException.conflict("upsert-auto-check-triggers requires pipeline_kind='auto_check' (got '"
					+ e.getPipelineKind() + "').");
		}
		if ("archived".equals(e.getStatus())) {
			throw ApiException.conflict("cannot modify bindings on an archived pipeline");
		}
		List<EventTypeBinding> bindings = parseRequiredBindings(req.eventTypes());
		BindingReplaceResult replaceResult = replaceBindings(id, bindings);

		Map<String, Object> body = new LinkedHashMap<>();
		body.put("pipeline_id", id);
		body.put("bindings", replaceResult.bindings);
		body.put("count", replaceResult.bindings.size());
		return body;
	}

	public List<PipelineDtos.AutoCheckTriggerView> listAutoCheckTriggers(Long id) {
		var rows = autoCheckTriggerRepository.findByPipelineId(id);
		List<PipelineDtos.AutoCheckTriggerView> out = new ArrayList<>();
		for (PipelineAutoCheckTriggerEntity t : rows) {
			Object filter = null;
			String mf = t.getMatchFilter();
			if (mf != null && !mf.isBlank()) {
				try { filter = mapper.readValue(mf, Map.class); }
				catch (Exception ignored) { filter = null; }
			}
			out.add(new PipelineDtos.AutoCheckTriggerView(
					t.getId(), t.getPipelineId(), t.getEventType(), filter, t.getCreatedAt()));
		}
		return out;
	}

	// ══════════════════════════════════════════════════════════════════════
	// Helpers
	// ══════════════════════════════════════════════════════════════════════

	/** Internal pair used while normalising the publish-auto-check body
	 *  before writing rows. */
	private record EventTypeBinding(String eventType, String matchFilterJson) {}

	private record BindingReplaceResult(LinkedHashSet<String> seen,
	                                    List<Map<String, Object>> bindings) {}

	/** Atomic binding replace shared by publishAutoCheck + upsertAutoCheckTriggers.
	 *  Deletes all existing rows, flushes (so unique constraint on
	 *  pipeline_id + event_type doesn't collide with the JPQL DELETE that
	 *  hasn't been flushed yet), then inserts the deduped new set. */
	private BindingReplaceResult replaceBindings(Long pipelineId, List<EventTypeBinding> bindings) {
		autoCheckTriggerRepository.deleteByPipelineId(pipelineId);
		autoCheckTriggerRepository.flush();
		LinkedHashSet<String> seen = new LinkedHashSet<>();
		List<Map<String, Object>> resultBindings = new ArrayList<>();
		for (EventTypeBinding b : bindings) {
			if (!seen.add(b.eventType)) continue;
			PipelineAutoCheckTriggerEntity t = new PipelineAutoCheckTriggerEntity();
			t.setPipelineId(pipelineId);
			t.setEventType(b.eventType);
			t.setMatchFilter(b.matchFilterJson);
			autoCheckTriggerRepository.save(t);
			Map<String, Object> rb = new LinkedHashMap<>();
			rb.put("event_type", b.eventType);
			rb.put("match_filter", b.matchFilterJson);
			resultBindings.add(rb);
		}
		return new BindingReplaceResult(seen, resultBindings);
	}

	/** Parse a heterogeneous (String | Object) event_types body, validate
	 *  non-empty, return canonical EventTypeBinding list. */
	private List<EventTypeBinding> parseRequiredBindings(List<Object> rawEventTypes) {
		if (rawEventTypes == null || rawEventTypes.isEmpty()) {
			throw ApiException.badRequest("event_types must contain at least one entry");
		}
		List<EventTypeBinding> bindings = new ArrayList<>();
		for (Object raw : rawEventTypes) {
			if (raw instanceof String s) {
				String trimmed = s.trim();
				if (!trimmed.isEmpty()) bindings.add(new EventTypeBinding(trimmed, null));
			} else if (raw instanceof Map<?, ?> m) {
				Object et = m.get("event_type");
				if (!(et instanceof String s) || s.isBlank()) continue;
				Object mf = m.get("match_filter");
				String mfJson = null;
				if (mf instanceof Map<?, ?> || mf instanceof List<?>) {
					try {
						mfJson = mapper.writeValueAsString(mf);
					} catch (JsonProcessingException ex) {
						throw ApiException.badRequest("match_filter for '" + s + "' is not serialisable: "
								+ ex.getMessage());
					}
				} else if (mf instanceof String s2 && !s2.isBlank()) {
					mfJson = s2;
				}
				bindings.add(new EventTypeBinding(s.trim(), mfJson));
			}
		}
		if (bindings.isEmpty()) {
			throw ApiException.badRequest("event_types must contain at least one valid entry");
		}
		return bindings;
	}

	/** Minimal server-side structural sanity for pipeline_json. Defense-in-depth
	 *  — frontend's PipelineValidator + sidecar's graph_build validator cover
	 *  the same rules, but pipeline 84 (2026-05-12) was persisted with edges
	 *  pointing to a non-existent node id, which crashed the executor at run
	 *  time. We now reject the save outright so a broken canvas can't reach
	 *  production.
	 *
	 *  <p>Checks (kept minimal to avoid duplicating the full Python validator):
	 *  pipeline_json parseable, node ids unique, every edge references a
	 *  known node id. Deeper rules (port type compat, block schema) still
	 *  live in the Python validator that fires on draft→validating→locked. */
	private void checkStructural(String pipelineJson) {
		if (pipelineJson == null || pipelineJson.isBlank()) return;
		Map<String, Object> pj;
		try {
			pj = mapper.readValue(pipelineJson, MAP_TYPE);
		} catch (JsonProcessingException ex) {
			throw ApiException.badRequest("pipeline_json is not valid JSON: " + ex.getOriginalMessage());
		}
		Set<String> nodeIds = new HashSet<>();
		Object nodesRaw = pj.get("nodes");
		if (nodesRaw instanceof List<?> nodesList) {
			for (Object n : nodesList) {
				if (!(n instanceof Map<?, ?> nm)) continue;
				Object id = nm.get("id");
				if (id == null) {
					throw ApiException.badRequest("pipeline node missing 'id'");
				}
				String sid = String.valueOf(id);
				if (!nodeIds.add(sid)) {
					throw ApiException.badRequest("duplicate node id in pipeline_json: " + sid);
				}
			}
		}
		Object edgesRaw = pj.get("edges");
		if (edgesRaw instanceof List<?> edgesList) {
			for (Object e : edgesList) {
				if (!(e instanceof Map<?, ?> em)) continue;
				Object from = em.containsKey("from_") ? em.get("from_") : em.get("from");
				Object to = em.get("to");
				String fromNode = (from instanceof Map<?, ?> fm) ? String.valueOf(fm.get("node")) : null;
				String toNode = (to instanceof Map<?, ?> tm) ? String.valueOf(tm.get("node")) : null;
				if (fromNode == null || toNode == null) {
					throw ApiException.badRequest("pipeline edge missing from/to endpoint");
				}
				if (!nodeIds.contains(fromNode)) {
					throw ApiException.badRequest(
							"pipeline edge references unknown source node '" + fromNode + "'. "
									+ "Available nodes: " + nodeIds);
				}
				if (!nodeIds.contains(toNode)) {
					throw ApiException.badRequest(
							"pipeline edge references unknown destination node '" + toNode + "'. "
									+ "Available nodes: " + nodeIds);
				}
			}
		}
	}

	private List<String> missingDocFields(Map<String, Object> doc) {
		List<String> required = List.of("slug", "name", "use_case", "inputs_schema", "outputs_schema");
		List<String> missing = new ArrayList<>();
		for (String f : required) {
			Object v = doc.get(f);
			if (v == null
					|| (v instanceof String s && s.isBlank())
					|| (v instanceof Collection<?> c && c.isEmpty())
					|| (v instanceof Map<?, ?> m && m.isEmpty())) {
				missing.add(f);
			}
		}
		return missing;
	}

	@SuppressWarnings("unchecked")
	private Map<String, Object> asMap(Object o) {
		return (o instanceof Map<?, ?>) ? (Map<String, Object>) o : Map.of();
	}

	private Map<String, Object> parsePipelineJson(String raw) {
		if (raw == null || raw.isBlank()) return new LinkedHashMap<>();
		try {
			return mapper.readValue(raw, MAP_TYPE);
		} catch (JsonProcessingException ex) {
			throw ApiException.badRequest("pipeline_json is not valid JSON: " + ex.getMessage());
		}
	}

	private String stringOrEmpty(Object o) {
		return o == null ? "" : String.valueOf(o);
	}

	private String jsonOr(Object o, String fallback) {
		try {
			return mapper.writeValueAsString(o);
		} catch (JsonProcessingException ex) {
			return fallback;
		}
	}
}
