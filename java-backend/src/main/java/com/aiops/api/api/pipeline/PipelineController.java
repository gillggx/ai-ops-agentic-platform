package com.aiops.api.api.pipeline;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
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
import jakarta.validation.constraints.NotBlank;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.Set;

@RestController
@RequestMapping("/api/v1/pipelines")
public class PipelineController {

	private final PipelineRepository repository;
	private final PublishedSkillRepository publishedSkillRepository;
	private final PipelineAutoCheckTriggerRepository autoCheckTriggerRepository;
	private final PipelineRunRepository pipelineRunRepository;
	private final PipelineDocGenerator docGenerator;
	private final ObjectMapper objectMapper;

	public PipelineController(PipelineRepository repository,
	                          PublishedSkillRepository publishedSkillRepository,
	                          PipelineAutoCheckTriggerRepository autoCheckTriggerRepository,
	                          PipelineRunRepository pipelineRunRepository,
	                          PipelineDocGenerator docGenerator,
	                          ObjectMapper objectMapper) {
		this.repository = repository;
		this.publishedSkillRepository = publishedSkillRepository;
		this.autoCheckTriggerRepository = autoCheckTriggerRepository;
		this.pipelineRunRepository = pipelineRunRepository;
		this.docGenerator = docGenerator;
		this.objectMapper = objectMapper;
	}

	@GetMapping
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<PipelineDtos.Summary>> list(@RequestParam(required = false) String status) {
		List<PipelineEntity> all = (status != null && !status.isBlank())
				? repository.findByStatus(status) : repository.findAll();
		return ApiResponse.ok(all.stream().map(PipelineDtos::summaryOf).toList());
	}

	@GetMapping("/{id}")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<PipelineDtos.Detail> get(@PathVariable Long id) {
		PipelineEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("pipeline"));
		return ApiResponse.ok(PipelineDtos.detailOf(e));
	}

	@PostMapping
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<PipelineDtos.Detail> create(@Validated @RequestBody PipelineDtos.CreateRequest req,
	                                               @AuthenticationPrincipal AuthPrincipal caller) {
		PipelineEntity e = new PipelineEntity();
		e.setName(req.name());
		if (req.description() != null) e.setDescription(req.description());
		if (req.pipelineKind() != null) e.setPipelineKind(req.pipelineKind());
		if (req.pipelineJson() != null) e.setPipelineJson(req.pipelineJson());
		if (req.version() != null) e.setVersion(req.version());
		e.setCreatedBy(caller.userId());
		return ApiResponse.ok(PipelineDtos.detailOf(repository.save(e)));
	}

	@PutMapping("/{id}")
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<PipelineDtos.Detail> update(@PathVariable Long id,
	                                               @Validated @RequestBody PipelineDtos.UpdateRequest req) {
		PipelineEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("pipeline"));
		if ("locked".equalsIgnoreCase(e.getStatus()) || "archived".equalsIgnoreCase(e.getStatus())) {
			throw ApiException.conflict("pipeline is " + e.getStatus() + "; cannot mutate");
		}
		if (req.name() != null) e.setName(req.name());
		if (req.description() != null) e.setDescription(req.description());
		if (req.pipelineKind() != null) e.setPipelineKind(req.pipelineKind());
		if (req.pipelineJson() != null) e.setPipelineJson(req.pipelineJson());
		if (req.autoDoc() != null) e.setAutoDoc(req.autoDoc());
		return ApiResponse.ok(PipelineDtos.detailOf(repository.save(e)));
	}

	// 5-stage lifecycle: draft → validating → locked → active → archived.
	// Phase 1 ports the state machine + timestamps; structural validation
	// (PipelineValidator + kind-specific checks) is deferred to Phase 2.
	private static final Map<String, Set<String>> ALLOWED_TRANSITIONS = Map.of(
			"draft",      Set.of("validating", "archived"),
			"validating", Set.of("locked", "draft"),
			"locked",     Set.of("active", "draft"),
			"active",     Set.of("archived"),
			"archived",   Set.of()
	);

	@PostMapping("/{id}/transition")
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<PipelineDtos.Detail> transition(@PathVariable Long id,
	                                                    @Validated @RequestBody PipelineDtos.TransitionRequest req) {
		PipelineEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("pipeline"));
		String from = e.getStatus();
		String to = req.to();
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
		return ApiResponse.ok(PipelineDtos.detailOf(repository.save(e)));
	}

	@PostMapping("/{id}/publish/draft-doc")
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<Map<String, Object>> publishDraftDoc(@PathVariable Long id) {
		PipelineEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("pipeline"));
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
			e.setAutoDoc(objectMapper.writeValueAsString(doc));
		} catch (JsonProcessingException ex) {
			throw new ApiException(org.springframework.http.HttpStatus.INTERNAL_SERVER_ERROR,
					"serialize_failed", "failed to serialize draft doc: " + ex.getMessage());
		}
		repository.save(e);
		return ApiResponse.ok(doc);
	}

	@PostMapping("/{id}/publish")
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<Map<String, Object>> publish(@PathVariable Long id,
	                                                 @Validated @RequestBody PipelineDtos.PublishRequest req) {
		PipelineEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("pipeline"));
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
		List<String> required = List.of("slug", "name", "use_case", "inputs_schema", "outputs_schema");
		List<String> missing = new java.util.ArrayList<>();
		for (String f : required) {
			Object v = doc.get(f);
			if (v == null || (v instanceof String s && s.isBlank())
					|| (v instanceof java.util.Collection<?> c && c.isEmpty())
					|| (v instanceof Map<?, ?> m && m.isEmpty())) {
				missing.add(f);
			}
		}
		if (!missing.isEmpty()) {
			throw new ApiException(org.springframework.http.HttpStatus.UNPROCESSABLE_ENTITY,
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

		Map<String, Object> result = new java.util.LinkedHashMap<>();
		result.put("id", e.getId());
		result.put("name", e.getName());
		result.put("status", e.getStatus());
		result.put("pipeline_kind", e.getPipelineKind());
		result.put("version", e.getVersion());
		result.put("published_slug", slug);
		return ApiResponse.ok(result);
	}

	@GetMapping("/{id}/runs")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<PipelineDtos.RunSummary>> listRuns(@PathVariable Long id,
	                                                            @RequestParam(defaultValue = "20") int limit) {
		int safe = Math.max(1, Math.min(limit, 200));
		List<PipelineRunEntity> all = pipelineRunRepository.findByPipelineIdOrderByStartedAtDesc(id);
		List<PipelineDtos.RunSummary> out = new java.util.ArrayList<>();
		for (int i = 0; i < Math.min(all.size(), safe); i++) {
			out.add(PipelineDtos.runSummaryOf(all.get(i)));
		}
		return ApiResponse.ok(out);
	}

	@PostMapping("/{id}/fork")
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<PipelineDtos.Detail> fork(@PathVariable Long id,
	                                              @AuthenticationPrincipal AuthPrincipal caller) {
		PipelineEntity src = repository.findById(id).orElseThrow(() -> ApiException.notFound("pipeline"));
		// PR-B: clone allowed from any non-draft state (including archived, so users
		// can revive retired pipelines). Drafts are already editable in place.
		if ("draft".equals(src.getStatus())) {
			throw ApiException.conflict("Cannot clone a draft — just edit it directly");
		}

		Map<String, Object> payload = parsePipelineJson(src.getPipelineJson());
		Object metaRaw = payload.get("metadata");
		Map<String, Object> meta = (metaRaw instanceof Map<?, ?>)
				? new java.util.LinkedHashMap<>(asMap(metaRaw))
				: new java.util.LinkedHashMap<>();
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
			forked.setPipelineJson(objectMapper.writeValueAsString(payload));
		} catch (JsonProcessingException ex) {
			throw new ApiException(org.springframework.http.HttpStatus.INTERNAL_SERVER_ERROR,
					"serialize_failed", "Failed to serialize pipeline_json: " + ex.getMessage());
		}
		return ApiResponse.ok(PipelineDtos.detailOf(repository.save(forked)));
	}

	@PostMapping("/{id}/publish-auto-check")
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<Map<String, Object>> publishAutoCheck(@PathVariable Long id,
	                                                          @Validated @RequestBody PipelineDtos.PublishAutoCheckRequest req) {
		PipelineEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("pipeline"));
		if (!"locked".equals(e.getStatus())) {
			throw ApiException.conflict("Pipeline must be 'locked' before publish (got '"
					+ e.getStatus() + "')");
		}
		if (!"auto_check".equals(e.getPipelineKind())) {
			throw ApiException.conflict("publish-auto-check is only for pipeline_kind='auto_check' (got '"
					+ e.getPipelineKind() + "').");
		}
		List<Object> rawEventTypes = req.eventTypes();
		if (rawEventTypes == null || rawEventTypes.isEmpty()) {
			throw ApiException.badRequest("event_types must contain at least one entry");
		}

		// Phase D — accept either of two body shapes:
		//   ["spc.ooc", "cpk.drop"]                                       (legacy)
		//   [{event_type: "spc.ooc", match_filter: {severity: ["HIGH"]}}] (new)
		// Build a normalised list of (event_type, match_filter_json | null) pairs
		// before writing rows so dedupe + write loop stays simple.
		List<EventTypeBinding> bindings = new java.util.ArrayList<>();
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
						mfJson = objectMapper.writeValueAsString(mf);
					} catch (JsonProcessingException ex) {
						throw ApiException.badRequest("match_filter for '" + s + "' is not serialisable: "
								+ ex.getMessage());
					}
				} else if (mf instanceof String s2 && !s2.isBlank()) {
					// already-stringified JSON — accept as-is
					mfJson = s2;
				}
				bindings.add(new EventTypeBinding(s.trim(), mfJson));
			}
		}
		if (bindings.isEmpty()) {
			throw ApiException.badRequest("event_types must contain at least one valid entry");
		}

		// Atomic replace: drop existing bindings, then insert the new set, then flip
		// pipeline → active. flush() so subsequent inserts in this transaction don't
		// collide with the (pipeline_id, event_type) unique constraint on rows that
		// the JPQL DELETE has already removed.
		autoCheckTriggerRepository.deleteByPipelineId(id);
		autoCheckTriggerRepository.flush();
		java.util.Set<String> seen = new java.util.LinkedHashSet<>();
		List<Map<String, Object>> resultBindings = new java.util.ArrayList<>();
		for (EventTypeBinding b : bindings) {
			if (!seen.add(b.eventType)) continue;
			PipelineAutoCheckTriggerEntity t = new PipelineAutoCheckTriggerEntity();
			t.setPipelineId(id);
			t.setEventType(b.eventType);
			t.setMatchFilter(b.matchFilterJson);
			autoCheckTriggerRepository.save(t);
			Map<String, Object> rb = new java.util.LinkedHashMap<>();
			rb.put("event_type", b.eventType);
			rb.put("match_filter", b.matchFilterJson);
			resultBindings.add(rb);
		}

		e.setStatus("active");
		e.setPublishedAt(OffsetDateTime.now());
		repository.save(e);

		Map<String, Object> result = new java.util.LinkedHashMap<>();
		result.put("id", e.getId());
		result.put("name", e.getName());
		result.put("status", e.getStatus());
		result.put("pipeline_kind", e.getPipelineKind());
		result.put("version", e.getVersion());
		result.put("event_types", new java.util.ArrayList<>(seen));
		result.put("bindings", resultBindings);
		return ApiResponse.ok(result);
	}

	/** Internal pair used while normalising the publish-auto-check body
	 *  before writing rows. */
	private record EventTypeBinding(String eventType, String matchFilterJson) {}

	@SuppressWarnings("unchecked")
	private Map<String, Object> asMap(Object o) {
		return (o instanceof Map<?, ?>) ? (Map<String, Object>) o : Map.of();
	}

	private Map<String, Object> parsePipelineJson(String raw) {
		if (raw == null || raw.isBlank()) return Map.of();
		try {
			return objectMapper.readValue(raw, new TypeReference<Map<String, Object>>() {});
		} catch (JsonProcessingException ex) {
			throw ApiException.badRequest("pipeline_json is not valid JSON: " + ex.getMessage());
		}
	}

	private String stringOrEmpty(Object o) {
		return o == null ? "" : String.valueOf(o);
	}

	private String jsonOr(Object o, String fallback) {
		try {
			return objectMapper.writeValueAsString(o);
		} catch (JsonProcessingException ex) {
			return fallback;
		}
	}

	@PostMapping("/{id}/archive")
	@Transactional
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public ApiResponse<PipelineDtos.Detail> archive(@PathVariable Long id) {
		PipelineEntity e = repository.findById(id).orElseThrow(() -> ApiException.notFound("pipeline"));
		e.setStatus("archived");
		e.setArchivedAt(OffsetDateTime.now());
		return ApiResponse.ok(PipelineDtos.detailOf(repository.save(e)));
	}

	@DeleteMapping("/{id}")
	@Transactional
	@PreAuthorize(Authorities.ADMIN)
	public ApiResponse<Void> delete(@PathVariable Long id) {
		if (!repository.existsById(id)) throw ApiException.notFound("pipeline");
		repository.deleteById(id);
		return ApiResponse.ok(null);
	}

	/** Phase D follow-up: list the auto_check trigger bindings for one
	 *  pipeline. Used by the canvas banner to show "this pipeline is
	 *  triggered by alarm.X / patrol Y" without having to open the modal. */
	@GetMapping("/{id}/auto-check-triggers")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<PipelineDtos.AutoCheckTriggerView>> listAutoCheckTriggers(@PathVariable Long id) {
		var rows = autoCheckTriggerRepository.findByPipelineId(id);
		List<PipelineDtos.AutoCheckTriggerView> out = new java.util.ArrayList<>();
		for (var t : rows) {
			Object filter = null;
			String mf = t.getMatchFilter();
			if (mf != null && !mf.isBlank()) {
				try { filter = objectMapper.readValue(mf, java.util.Map.class); }
				catch (Exception ignored) { filter = null; }
			}
			out.add(new PipelineDtos.AutoCheckTriggerView(
					t.getId(), t.getPipelineId(), t.getEventType(), filter, t.getCreatedAt()));
		}
		return ApiResponse.ok(out);
	}

	public static final class PipelineDtos {

		public record Summary(Long id, String name, String description, String status,
		                      String pipelineKind, String version, Long createdBy,
		                      java.time.OffsetDateTime updatedAt) {}

		public record AutoCheckTriggerView(Long id, Long pipelineId, String eventType,
		                                   Object matchFilter, java.time.OffsetDateTime createdAt) {}

		public record Detail(Long id, String name, String description, String status,
		                     String pipelineKind, String version, String pipelineJson,
		                     String usageStats, String autoDoc, Long createdBy, Long approvedBy,
		                     Long parentId, OffsetDateTime createdAt, OffsetDateTime updatedAt,
		                     OffsetDateTime lockedAt, OffsetDateTime publishedAt,
		                     OffsetDateTime archivedAt) {}

		public record CreateRequest(@NotBlank String name, String description, String pipelineKind,
		                            String pipelineJson, String version) {}

		public record UpdateRequest(String name, String description, String pipelineKind,
		                            String pipelineJson, String autoDoc) {}

		public record TransitionRequest(@NotBlank String to, String notes) {}

		public record PublishRequest(Map<String, Object> reviewedDoc, String publishedBy) {}

		/** Phase D — body accepts a heterogeneous list:
		 *    ["spc.ooc", "cpk.drop"]
		 *  OR
		 *    [{event_type: "spc.ooc", match_filter: {severity: ["HIGH"]}}, ...]
		 *  Each element is either a String (legacy) or an Object with
		 *  {event_type, match_filter?}. PipelineController.publish_auto_check
		 *  normalises both shapes before writing trigger rows. */
		public record PublishAutoCheckRequest(
				@jakarta.validation.constraints.NotNull
				@jakarta.validation.constraints.Size(min = 1, message = "event_types must contain at least one entry")
				List<Object> eventTypes) {}

		public record RunSummary(Long id, Long pipelineId, String pipelineVersion,
		                         String triggeredBy, String status,
		                         String nodeResults, String errorMessage,
		                         OffsetDateTime startedAt, OffsetDateTime finishedAt) {}

		static RunSummary runSummaryOf(PipelineRunEntity e) {
			return new RunSummary(e.getId(), e.getPipelineId(), e.getPipelineVersion(),
					e.getTriggeredBy(), e.getStatus(),
					e.getNodeResults(), e.getErrorMessage(),
					e.getStartedAt(), e.getFinishedAt());
		}

		static Summary summaryOf(PipelineEntity e) {
			return new Summary(e.getId(), e.getName(), e.getDescription(), e.getStatus(),
					e.getPipelineKind(), e.getVersion(), e.getCreatedBy(), e.getUpdatedAt());
		}

		static Detail detailOf(PipelineEntity e) {
			return new Detail(e.getId(), e.getName(), e.getDescription(), e.getStatus(),
					e.getPipelineKind(), e.getVersion(), e.getPipelineJson(), e.getUsageStats(),
					e.getAutoDoc(), e.getCreatedBy(), e.getApprovedBy(), e.getParentId(),
					e.getCreatedAt(), e.getUpdatedAt(), e.getLockedAt(), e.getPublishedAt(),
					e.getArchivedAt());
		}
	}
}
