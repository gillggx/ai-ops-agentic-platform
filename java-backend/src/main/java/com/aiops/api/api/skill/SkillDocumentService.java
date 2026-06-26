package com.aiops.api.api.skill;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.JsonUtils;
import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.domain.event.EventTypeRepository;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.skill.SkillDocumentEntity;
import com.aiops.api.domain.skill.SkillDocumentRepository;
import com.aiops.api.domain.skill.SkillRunEntity;
import com.aiops.api.domain.skill.SkillRunRepository;
import com.aiops.api.sidecar.PythonSidecarClient;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * Skill Document business logic.
 *
 * <p>Extracted from {@code SkillDocumentController} 2026-05-23 as part of
 * the Java OOP refactor (Phase 12). Controllers should only handle HTTP
 * concerns (parameter binding, response wrapping, security annotations);
 * all entity manipulation, validation, JSON serdes, sidecar calls, and
 * cross-entity coordination lives here.
 *
 * <p>Methods raise {@link ApiException} for client-facing errors; runtime
 * errors leak as RuntimeException so {@code @ControllerAdvice} can map
 * them to 500 with stack preserved (no silent swallow).
 *
 * <p>The SSE {@code run()} endpoint stays in the controller — its body
 * is pure HTTP-transport plumbing around {@code SkillRunnerService.run()}
 * which already returns a reactive {@code Flux<RunnerEvent>}.
 */
@Slf4j
@Service
public class SkillDocumentService {

    static final Set<String> VALID_STAGES = Set.of("patrol", "diagnose");
    static final Set<String> VALID_STATUS = Set.of("draft", "stable");
    static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};
    static final TypeReference<List<Map<String, Object>>> LIST_MAP_TYPE = new TypeReference<>() {};
    static final Duration SIDECAR_TIMEOUT = Duration.ofMinutes(2);

    private final SkillDocumentRepository repository;
    private final SkillRunRepository runRepository;
    private final ObjectMapper mapper;
    private final AlarmRepository alarmRepo;
    private final PipelineRepository pipelineRepo;
    private final EventTypeRepository eventTypeRepo;
    private final SkillMaterializeService materializer;
    private final PythonSidecarClient sidecar;

    public SkillDocumentService(SkillDocumentRepository repository,
                                SkillRunRepository runRepository,
                                ObjectMapper mapper,
                                AlarmRepository alarmRepo,
                                PipelineRepository pipelineRepo,
                                EventTypeRepository eventTypeRepo,
                                SkillMaterializeService materializer,
                                PythonSidecarClient sidecar) {
        this.repository = repository;
        this.runRepository = runRepository;
        this.mapper = mapper;
        this.alarmRepo = alarmRepo;
        this.pipelineRepo = pipelineRepo;
        this.eventTypeRepo = eventTypeRepo;
        this.materializer = materializer;
        this.sidecar = sidecar;
    }

    // ── Reads ────────────────────────────────────────────────────────────────

    /** Library listing. Empty/blank stage → return all; otherwise filter. */
    public List<SkillDocumentEntity> list(String stage) {
        if (stage == null || stage.isBlank()) {
            return repository.findAll();
        }
        return repository.findByStage(stage);
    }

    /** Fetch single by slug or 404. */
    public SkillDocumentEntity getBySlug(String slug) {
        return repository.findBySlug(slug)
                .orElseThrow(() -> ApiException.notFound("skill"));
    }

    public List<SkillRunEntity> listRuns(String slug, Boolean test) {
        SkillDocumentEntity e = getBySlug(slug);
        return (test == null)
                ? runRepository.findBySkillIdOrderByTriggeredAtDesc(e.getId())
                : runRepository.findBySkillIdAndIsTestOrderByTriggeredAtDesc(e.getId(), test);
    }

    // ── Writes — basic CRUD ──────────────────────────────────────────────────

    /** Create a new draft skill from a CreateRequest. Auto-derives slug/stage
     *  when caller omits them (Phase 11 v11 simplified-form support). */
    @Transactional
    public SkillDocumentEntity create(Dtos.CreateRequest req, AuthPrincipal caller) {
        String stage = req.stage();
        if (stage == null || stage.isBlank()) {
            // Safe default; PUT auto-flips to patrol on schedule trigger
            stage = "diagnose";
        } else if (!VALID_STAGES.contains(stage)) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "validation_error",
                    "stage must be patrol|diagnose");
        }

        String slug = req.slug();
        if (slug == null || slug.isBlank()) {
            slug = autoSlug(req.title());
        }
        if (repository.existsBySlug(slug)) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "duplicate_slug",
                    "slug already exists: " + slug);
        }

        SkillDocumentEntity e = new SkillDocumentEntity();
        e.setSlug(slug);
        e.setTitle(req.title());
        e.setStage(stage);
        e.setDomain(Objects.requireNonNullElse(req.domain(), ""));
        e.setDescription(Objects.requireNonNullElse(req.description(), ""));
        e.setAuthorUserId(caller != null ? caller.userId() : null);
        e.setVersion(Objects.requireNonNullElse(req.version(), "0.1"));
        e.setStatus("draft");
        e.setTriggerConfig(Objects.requireNonNullElse(req.triggerConfig(), "{}"));
        e.setSteps(Objects.requireNonNullElse(req.steps(), "[]"));

        SkillDocumentEntity saved = repository.save(e);
        log.info("skill created: id={} slug={} stage={} author={}",
                saved.getId(), saved.getSlug(), stage, e.getAuthorUserId());
        return saved;
    }

    @Transactional
    /**
     * Set only the lifecycle status (draft|stable). Used by the UI-handoff
     * resolve path (confirm_activate / confirm_disable) where Dtos is not
     * visible. Goes through {@link #update} so trigger materialize/clear on
     * status transitions still fires.
     */
    public SkillDocumentEntity setStatus(String slug, String status) {
        return update(slug, new Dtos.UpdateRequest(null, null, status, null, null, null, null, null, null, null));
    }

    public SkillDocumentEntity update(String slug, Dtos.UpdateRequest req) {
        SkillDocumentEntity e = getBySlug(slug);
        if (req.title() != null) e.setTitle(req.title());
        if (req.stage() != null) {
            if (!VALID_STAGES.contains(req.stage())) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "validation_error",
                        "stage must be patrol|diagnose");
            }
            e.setStage(req.stage());
        }
        String oldStatus = e.getStatus();
        if (req.status() != null) {
            if (!VALID_STATUS.contains(req.status())) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "validation_error",
                        "status must be draft|stable");
            }
            e.setStatus(req.status());
        }
        if (req.domain() != null) e.setDomain(req.domain());
        if (req.description() != null) e.setDescription(req.description());
        if (req.certifiedBy() != null) e.setCertifiedBy(req.certifiedBy());
        if (req.version() != null) e.setVersion(req.version());
        if (req.triggerConfig() != null) {
            e.setTriggerConfig(req.triggerConfig());
            // Phase 11 v11 — auto-flip stage from trigger.type unless caller
            // explicitly set stage in the same request. schedule → patrol,
            // event → diagnose. Lets the simplified New Skill form skip stage
            // entirely and have it land on the right value once trigger is set.
            if (req.stage() == null) {
                String derived = stageFromTrigger(req.triggerConfig());
                if (derived != null && !derived.equals(e.getStage())) {
                    log.info("skill {}: stage auto-flipped {} → {} (from trigger.type)",
                            e.getSlug(), e.getStage(), derived);
                    e.setStage(derived);
                }
            }
        }
        if (req.steps() != null) e.setSteps(req.steps());
        // Phase 11 v2: confirmCheck is nullable — empty string clears the gate,
        // a JSON blob installs/replaces it. We can't distinguish "field absent"
        // from "null" in record DTOs cleanly, so the convention is: caller MUST
        // send confirmCheck="" to clear, or omit the entire field to leave it.
        if (req.confirmCheck() != null) {
            e.setConfirmCheck(req.confirmCheck().isBlank() ? null : req.confirmCheck());
        }

        // Phase 11 — materialize / clear trigger rows on status transitions.
        String newStatus = e.getStatus();
        if (!Objects.equals(oldStatus, newStatus)) {
            if ("stable".equals(newStatus)) {
                int n = materializer.materialize(e);
                log.info("skill {} published (stable) — materialized {} rows", e.getSlug(), n);
            } else if ("draft".equals(newStatus) && "stable".equals(oldStatus)) {
                int n = materializer.clear(e);
                log.info("skill {} unpublished (draft) — cleared {} rows", e.getSlug(), n);
            }
        } else if ("stable".equals(newStatus)
                && (req.triggerConfig() != null || req.steps() != null || req.confirmCheck() != null)) {
            // Already published and trigger/steps/confirm changed → re-materialize.
            int n = materializer.materialize(e);
            log.info("skill {} re-materialized {} rows after stable-edit", e.getSlug(), n);
        }
        return e;
    }

    @Transactional
    public void delete(String slug) {
        SkillDocumentEntity e = getBySlug(slug);
        // Clear materialized trigger rows first so we don't leave dangling
        // auto_patrols / auto_check rows pointing at a deleted skill.
        materializer.clear(e);
        repository.delete(e);
    }

    // ── Confirm-check slot ───────────────────────────────────────────────────

    /** Translate {@code text} into a confirm-check pipeline via sidecar,
     *  persist as pb_pipeline row, and write the JSON blob into
     *  skill.confirm_check. Mirrors {@link #addStep}. */
    @Transactional
    public SkillDocumentEntity setConfirmCheck(String slug, String text, AuthPrincipal caller) {
        if (text == null || text.isBlank()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "validation_error", "text required");
        }
        SkillDocumentEntity skill = getBySlug(slug);

        Map<String, Object> result = translateStep(text, caller, "confirm-check");
        String resStatus = String.valueOf(result.getOrDefault("status", ""));
        Object pj = result.get("pipeline_json");
        String summary = String.valueOf(result.getOrDefault("summary", ""));

        Long pipelineId = null;
        String aiSummary = summary;
        if ("finished".equals(resStatus) && pj instanceof Map) {
            pipelineId = persistTranslatedPipeline(skill, pj, text, "confirm", caller);
        } else {
            aiSummary = "(translation 失敗) "
                    + result.getOrDefault("error_message", "translation incomplete");
        }

        Map<String, Object> confirm = new HashMap<>();
        confirm.put("description", text);
        confirm.put("ai_summary", aiSummary);
        confirm.put("pipeline_id", pipelineId);
        confirm.put("must_pass", true);          // default; UI can flip later
        try {
            skill.setConfirmCheck(mapper.writeValueAsString(confirm));
        } catch (JsonProcessingException e) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "confirm_serialization", e.getMessage());
        }
        return skill;
    }

    @Transactional
    public SkillDocumentEntity clearConfirmCheck(String slug) {
        SkillDocumentEntity skill = getBySlug(slug);
        skill.setConfirmCheck(null);
        return skill;
    }

    // ── Steps ────────────────────────────────────────────────────────────────

    /** Phase 11 — translate NL step into pipeline (ending in block_step_check),
     *  persist as pb_pipeline row, append to skill.steps[]. */
    @Transactional
    public SkillDocumentEntity addStep(String slug, String text, AuthPrincipal caller) {
        if (text == null || text.isBlank()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "validation_error", "text required");
        }
        SkillDocumentEntity skill = getBySlug(slug);

        Map<String, Object> result = translateStep(text, caller, "addStep");
        String resStatus = String.valueOf(result.getOrDefault("status", ""));
        Object pj = result.get("pipeline_json");
        String summary = String.valueOf(result.getOrDefault("summary", ""));
        if (!"finished".equals(resStatus) || !(pj instanceof Map)) {
            String err = String.valueOf(result.getOrDefault("error_message", "translation incomplete"));
            return appendStep(skill, text, null, "(translation 失敗) " + err);
        }

        Long pipelineId = persistTranslatedPipeline(skill, pj, text, "step", caller);
        return appendStep(skill, text, pipelineId, summary);
    }

    // ── Builder embed wiring ─────────────────────────────────────────────────

    /** Build the Pipeline-Builder URL the frontend opens for a given slot.
     *  Returns {builder_url, skill_id, slot}. */
    public Map<String, Object> builderUrl(String slug, String slot, String instruction) {
        if (!slot.equals("confirm") && !slot.startsWith("step:")) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "validation_error",
                    "slot must be 'confirm' or 'step:<id>'");
        }
        SkillDocumentEntity skill = getBySlug(slug);

        Map<String, Object> trig = JsonUtils.parseObject(mapper, skill.getTriggerConfig());
        StringBuilder qs = new StringBuilder();
        qs.append("?embed=skill")
          .append("&skill_slug=").append(URLEncoder.encode(slug, StandardCharsets.UTF_8))
          .append("&skill_doc_id=").append(skill.getId())
          .append("&slot=").append(URLEncoder.encode(slot, StandardCharsets.UTF_8));
        if (instruction != null && !instruction.isBlank()) {
            qs.append("&instruction=").append(URLEncoder.encode(instruction, StandardCharsets.UTF_8));
        }
        // Phase 11 v6 — if slot already has a bound pipeline, carry its id so
        // Builder embed mode loads the existing JSON instead of dropping the
        // user onto a blank canvas. Refine = update same row.
        Long existingPipelineId = lookupSlotPipelineId(skill, slot);
        if (existingPipelineId != null) {
            qs.append("&existing_pipeline_id=").append(existingPipelineId);
        }
        String type = String.valueOf(trig.getOrDefault("type", "event"));
        if ("system".equals(type)) type = "event";  // legacy alias
        qs.append("&trigger_type=").append(URLEncoder.encode(type, StandardCharsets.UTF_8));
        if ("event".equals(type)) {
            String ev = String.valueOf(trig.getOrDefault("event",
                    trig.getOrDefault("event_type", "")));
            if (!ev.isBlank()) qs.append("&trigger_event=").append(URLEncoder.encode(ev, StandardCharsets.UTF_8));
        } else if ("schedule".equals(type)) {
            Object targetObj = trig.get("target");
            if (targetObj instanceof Map<?, ?> tm) {
                Object kind = tm.get("kind");
                if (kind != null) qs.append("&target_kind=").append(URLEncoder.encode(String.valueOf(kind), StandardCharsets.UTF_8));
                Object ids = tm.get("ids");
                if (ids instanceof List<?> idList && !idList.isEmpty()) {
                    String joined = String.join(",", idList.stream().map(String::valueOf).toList());
                    qs.append("&target_ids=").append(URLEncoder.encode(joined, StandardCharsets.UTF_8));
                }
            }
        }

        // Phase 11 v6 — refine path: existing pipeline → /[id] edit route
        // already loads the pipeline_json + supports Glass Box / inputs
        // editing. The Skill embed query params still flow through so the
        // banner + bind callback work the same way.
        String basePath = (existingPipelineId != null)
                ? ("/admin/pipeline-builder/" + existingPipelineId)
                : "/admin/pipeline-builder/new";
        String url = basePath + qs;
        return Map.of(
                "builder_url", url,
                "skill_id",    skill.getId(),
                "slot",        slot
        );
    }

    /** Pipeline-Builder calls this on Confirm to bind the just-built pipeline
     *  back into the requesting skill's slot. */
    @Transactional
    public SkillDocumentEntity bindPipeline(String slug, Map<String, Object> body) {
        SkillDocumentEntity skill = getBySlug(slug);
        String slot = String.valueOf(body.getOrDefault("slot", "")).trim();
        Object pid = body.get("pipeline_id");
        if (!(pid instanceof Number pn)) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "validation_error", "pipeline_id required");
        }
        Long pipelineId = pn.longValue();
        String summary = String.valueOf(body.getOrDefault("summary", ""));
        String description = String.valueOf(body.getOrDefault("description", summary));

        // Stamp ownership on the pipeline row so future cleanup / lifecycle
        // logic can find skill-bound pipelines.
        PipelineEntity pe = pipelineRepo.findById(pipelineId)
                .orElseThrow(() -> ApiException.notFound("pipeline"));
        pe.setParentSkillDocId(skill.getId());
        pe.setParentSlot(slot);
        // Phase 11 v4: under Skill ownership, lifecycle is driven by Skill.
        // Park the pipeline at status="linked" so it doesn't show up in
        // the free-standing pipeline list as draft / orphan.
        pe.setStatus("linked");
        pipelineRepo.save(pe);

        if ("confirm".equals(slot)) {
            Map<String, Object> confirm = new HashMap<>();
            confirm.put("description", description);
            confirm.put("ai_summary", summary);
            confirm.put("pipeline_id", pipelineId);
            confirm.put("must_pass", true);
            try {
                skill.setConfirmCheck(mapper.writeValueAsString(confirm));
            } catch (JsonProcessingException e) {
                throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "confirm_serialization", e.getMessage());
            }
        } else if (slot.startsWith("step:")) {
            String stepId = slot.substring("step:".length());
            updateStepPipelineId(skill, stepId, pipelineId, description, summary);
        } else {
            throw new ApiException(HttpStatus.BAD_REQUEST, "validation_error",
                    "slot must be 'confirm' or 'step:<id|NEW>'");
        }
        return skill;
    }

    // ── Past-event replay sources ───────────────────────────────────────────

    /** Phase 11 — past trigger payloads for the Test modal's "From past
     *  event" tab. system|event → alarms, schedule → past skill_runs. */
    public List<Map<String, Object>> pastEvents(String slug) {
        SkillDocumentEntity skill = getBySlug(slug);
        Map<String, Object> trig = JsonUtils.parseObject(mapper, skill.getTriggerConfig());
        String type = String.valueOf(trig.getOrDefault("type", "schedule"));
        List<Map<String, Object>> out = new ArrayList<>();

        if ("system".equals(type) || "event".equals(type)) {
            // 2026-05-12: was only matching "system" + reading "event_type" key, but
            // the canonical trigger_config schema is {"type":"event","event":"OOC"}
            // (e.g. skill 42 demo-ocap-5in3out). The legacy "system" + "event_type"
            // form is still produced by some imports — accept both.
            String eventType = String.valueOf(trig.getOrDefault("event",
                    trig.getOrDefault("event_type", "")));
            if (!eventType.isBlank()) {
                // event_types.attributes lets test payload mirror what the runtime
                // would actually deliver (alarm rows carry 4-5 canonical fields;
                // declared inputs may reference more).
                List<Map<String, Object>> attrSchema = lookupEventAttrSchema(eventType);
                List<AlarmEntity> alarms = alarmRepo.findTop30ByTriggerEventOrderByCreatedAtDesc(eventType);
                for (AlarmEntity a : alarms) {
                    Map<String, Object> tc = new HashMap<>();
                    tc.put("id", "hc-" + a.getId());
                    tc.put("kind", "historical");
                    tc.put("title", a.getTitle() != null && !a.getTitle().isBlank() ? a.getTitle() : eventType);
                    tc.put("desc", "Past " + eventType + " on " + a.getEquipmentId());
                    Map<String, Object> meta = new HashMap<>();
                    meta.put("tool", a.getEquipmentId());
                    meta.put("lot", a.getLotId());
                    meta.put("time", a.getEventTime() != null ? a.getEventTime().toString() : null);
                    meta.put("outcome", a.getStatus());
                    tc.put("meta", meta);
                    tc.put("payload", buildEventPayload(a, eventType, attrSchema));
                    out.add(tc);
                }
            }
        } else if ("user".equals(type)) {
            // user-defined rule fires are tied to a materialized auto_patrol row.
            // If not yet materialized, list is empty (no synthetic fallback today).
        } else {
            // schedule: surface past skill_runs (excluding tests) as replay sources
            List<SkillRunEntity> runs = runRepository.findBySkillIdAndIsTestOrderByTriggeredAtDesc(skill.getId(), false);
            int n = Math.min(runs.size(), 30);
            for (int i = 0; i < n; i++) {
                SkillRunEntity r = runs.get(i);
                Map<String, Object> tc = new HashMap<>();
                tc.put("id", "sr-" + r.getId());
                tc.put("kind", "historical");
                tc.put("title", "Past run #" + r.getId());
                tc.put("desc", "Run at " + r.getTriggeredAt());
                Map<String, Object> meta = new HashMap<>();
                meta.put("time", r.getTriggeredAt() != null ? r.getTriggeredAt().toString() : null);
                meta.put("outcome", r.getStatus());
                tc.put("meta", meta);
                tc.put("payload", JsonUtils.parseObject(mapper, r.getTriggerPayload()));
                out.add(tc);
            }
        }
        return out;
    }

    // ── Helpers (package-private so other services in this package can reuse) ──

    /** Slugify a title for skills created without an explicit slug.
     *  ASCII letters/digits/dashes only (lowercased); CJK / other chars
     *  collapse into a {@code skill-{epochSec}} fallback so we always
     *  produce a valid URL fragment. */
    static String autoSlug(String title) {
        String base = title == null ? "" : title.toLowerCase()
                .replaceAll("[^a-z0-9\\-\\s]", "")
                .trim()
                .replaceAll("\\s+", "-");
        if (base.length() < 2) base = "skill";
        long ts = System.currentTimeMillis() / 1000L;
        // Cap base to 40 chars so the final slug stays under 60.
        return (base.length() > 40 ? base.substring(0, 40) : base)
                + "-" + Long.toString(ts, 36);
    }

    /** Derive stage from trigger.type. schedule → patrol; event → diagnose.
     *  Returns null if trigger is unparseable / absent. */
    String stageFromTrigger(String triggerConfigJson) {
        if (triggerConfigJson == null || triggerConfigJson.isBlank()) return null;
        try {
            Map<String, Object> tc = mapper.readValue(triggerConfigJson, MAP_TYPE);
            Object t = tc.get("type");
            if (t == null) return null;
            String s = String.valueOf(t).toLowerCase();
            if ("schedule".equals(s)) return "patrol";
            if ("event".equals(s) || "system".equals(s)) return "diagnose";
            return null;
        } catch (JsonProcessingException ex) {
            // Bad JSON in trigger_config → can't derive; let caller fall back.
            log.debug("stageFromTrigger: parse failed for trigger_config — {}", ex.toString());
            return null;
        }
    }

    /** Call sidecar /agent/skill/translate-step and return the raw map.
     *  Wraps Mono.block() with proper timeout + ApiException translation
     *  so the caller doesn't deal with WebClient exceptions. */
    @SuppressWarnings({"unchecked", "rawtypes"})
    private Map<String, Object> translateStep(String text, AuthPrincipal caller, String tag) {
        Map<String, Object> req = Map.of("text", text);
        Map result;
        try {
            result = sidecar.postJson("/internal/agent/skill/translate-step", req, Map.class, caller)
                    .block(SIDECAR_TIMEOUT);
        } catch (RuntimeException ex) {
            // Block() wraps WebClient errors + timeouts in unchecked exceptions
            // (WebClientResponseException / IllegalStateException for timeout).
            // Catch RuntimeException, not Exception — bubble checked errors.
            log.warn("{} translate failed: {}", tag, ex.toString());
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "translate_failed",
                    "sidecar unavailable: " + ex.getMessage());
        }
        if (result == null) {
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "translate_failed",
                    "sidecar returned null");
        }
        return (Map<String, Object>) result;
    }

    /** Persist a sidecar-translated pipeline_json as a draft pb_pipeline row
     *  and return its new id. {@code slot} is "confirm" | "step" — used
     *  only for the row's display name suffix. */
    private Long persistTranslatedPipeline(SkillDocumentEntity skill, Object pipelineJson,
                                           String text, String slot, AuthPrincipal caller) {
        PipelineEntity pe = new PipelineEntity();
        pe.setName("[Skill] " + skill.getTitle() + " · " + slot);
        pe.setDescription(text);
        pe.setStatus("draft");
        pe.setPipelineKind("diagnostic");
        try {
            pe.setPipelineJson(mapper.writeValueAsString(pipelineJson));
        } catch (JsonProcessingException e) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "pipeline_save_failed", e.getMessage());
        }
        pe.setCreatedBy(caller != null ? caller.userId() : null);
        return pipelineRepo.save(pe).getId();
    }

    /** Pull event_types.attributes for an event name. Empty list when not
     *  registered or JSON parse fails — buildEventPayload then falls back
     *  to canonical alarm-derived fields. */
    private List<Map<String, Object>> lookupEventAttrSchema(String eventName) {
        try {
            return eventTypeRepo.findByName(eventName)
                    .map(et -> {
                        String raw = et.getAttributes();
                        if (raw == null || raw.isBlank()) return Collections.<Map<String, Object>>emptyList();
                        try {
                            return mapper.readValue(raw, LIST_MAP_TYPE);
                        } catch (JsonProcessingException ignore) { return Collections.<Map<String, Object>>emptyList(); }
                    })
                    .orElseGet(Collections::emptyList);
        } catch (RuntimeException e) {
            // findByName + lambda chain can throw JPA exceptions (DataAccess /
            // JpaSystem) wrapped as RuntimeException; never break the alarm
            // payload build chain — return empty schema (canonical fields used).
            log.debug("lookupEventAttrSchema for '{}' failed — {}", eventName, e.toString());
            return Collections.emptyList();
        }
    }

    /** Build a test payload for a past alarm. Starts with alarm-derived
     *  canonical fields, then iterates event_types.attributes and fills any
     *  declared field not already set with a sensible default, so pipeline
     *  test gets EVERY referenced field even when the alarm row doesn't
     *  carry it (parameter, ooc_details, chamber_id, etc.). */
    private Map<String, Object> buildEventPayload(AlarmEntity a, String eventName,
                                                  List<Map<String, Object>> attrSchema) {
        Map<String, Object> payload = new HashMap<>();
        // Alarm-canonical fields under multiple names so pipelines wired with
        // either tool_id or equipment_id (canonical OOC schema) both resolve.
        payload.put("event_type", eventName);
        payload.put("alarm_id", a.getId());
        payload.put("tool_id", a.getEquipmentId());
        payload.put("equipment_id", a.getEquipmentId());
        payload.put("lot_id", a.getLotId());
        payload.put("step", a.getStep());
        payload.put("step_id", a.getStep());
        payload.put("severity", a.getSeverity());
        String t = a.getEventTime() != null ? a.getEventTime().toString() : null;
        payload.put("event_time", t);
        payload.put("timestamp", t);
        payload.put("process_timestamp", t);

        for (Map<String, Object> attr : attrSchema) {
            Object nameObj = attr.get("name");
            if (!(nameObj instanceof String name) || name.isBlank()) continue;
            if (payload.get(name) != null) continue;
            String type = String.valueOf(attr.getOrDefault("type", "string"));
            payload.put(name, defaultForAttr(name, type));
        }
        return payload;
    }

    private static Object defaultForAttr(String name, String type) {
        return switch (name) {
            case "tool_id", "equipment_id" -> "EQP-01";
            case "lot_id" -> "LOT-0001";
            case "step", "step_id" -> "STEP_001";
            case "chamber_id" -> "CH-1";
            case "recipe_id" -> "RECIPE-A";
            case "parameter", "ooc_parameter" -> "CD_Mean";
            case "spc_chart", "SPC_CHART" -> "spc_xbar";
            case "fault_code" -> "FDC_RGA_H2O_HIGH";
            case "severity" -> "warning";
            default -> switch (type) {
                case "integer", "number" -> 0;
                case "boolean" -> Boolean.FALSE;
                case "object" -> Map.of();
                case "array" -> List.of();
                default -> "";
            };
        };
    }

    /** Phase 11 v6 — find the pipeline_id currently bound to {@code slot} on
     *  this skill (or {@code null} if unbound). Used by builder-url to seed
     *  the Builder embed mode with the existing pipeline so "Refine" doesn't
     *  drop the user onto a blank canvas.
     *
     *  <p>Also verifies the pipeline still exists — JSON refs on
     *  skill_documents don't have a pg-managed FK so out-of-band deletes
     *  (V26 cleanup, manual psql, race) can leave dangling ids. Returning
     *  null here lets builder-url fall back to /new + lets the UI show the
     *  C1 / step card as "needs rebuild" rather than chasing a 404. */
    private Long lookupSlotPipelineId(SkillDocumentEntity skill, String slot) {
        Long candidate = null;
        if ("confirm".equals(slot)) {
            Map<String, Object> cc = JsonUtils.parseObject(mapper, skill.getConfirmCheck());
            Object pid = cc.get("pipeline_id");
            candidate = (pid instanceof Number n) ? n.longValue() : null;
        } else if (slot.startsWith("step:") && !"step:NEW".equalsIgnoreCase(slot)) {
            String stepId = slot.substring("step:".length());
            try {
                List<Map<String, Object>> stepsList = mapper.readValue(
                        skill.getSteps() == null || skill.getSteps().isBlank() ? "[]" : skill.getSteps(),
                        LIST_MAP_TYPE);
                for (Map<String, Object> s : stepsList) {
                    if (stepId.equals(String.valueOf(s.get("id")))) {
                        Object pid = s.get("pipeline_id");
                        candidate = (pid instanceof Number n) ? n.longValue() : null;
                        break;
                    }
                }
            } catch (JsonProcessingException ignored) {}
        }
        if (candidate != null && !pipelineRepo.existsById(candidate)) {
            log.info("skill {} slot {} ref pipeline {} no longer exists — treating as unbound",
                    skill.getSlug(), slot, candidate);
            return null;
        }
        return candidate;
    }

    /** Append a brand-new step (created from sidecar translation) to
     *  skill.steps[] and write back the JSON. {@code pipelineId} may be null
     *  when translation failed — step lands in pending state so the user can
     *  iterate. */
    private SkillDocumentEntity appendStep(SkillDocumentEntity skill, String text,
                                            Long pipelineId, String aiSummary) {
        try {
            List<Map<String, Object>> stepsList = mapper.readValue(
                    skill.getSteps() == null || skill.getSteps().isBlank() ? "[]" : skill.getSteps(),
                    LIST_MAP_TYPE);
            String newId = "s" + (stepsList.size() + 1) + "_" + Long.toHexString(System.currentTimeMillis());
            Map<String, Object> step = new HashMap<>();
            step.put("id", newId);
            step.put("order", stepsList.size() + 1);
            step.put("text", text);
            step.put("ai_summary", aiSummary);
            step.put("pipeline_id", pipelineId);
            step.put("confirmed", false);
            step.put("pending", true);
            step.put("suggested_actions", List.of());
            step.put("badge", Map.of("kind", "ai", "label", pipelineId != null ? "AI Generated" : "Pending"));
            stepsList.add(step);
            skill.setSteps(mapper.writeValueAsString(stepsList));
            return skill;
        } catch (JsonProcessingException e) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "steps_serialization", e.getMessage());
        }
    }

    /** Update an existing step's pipeline_id (or append if {@code stepId} is
     *  "NEW" / doesn't exist). Used by bindPipeline after the Builder calls
     *  back with a freshly-built pipeline. */
    private void updateStepPipelineId(SkillDocumentEntity skill, String stepId,
                                      Long pipelineId, String description, String summary) {
        try {
            List<Map<String, Object>> stepsList = mapper.readValue(
                    skill.getSteps() == null || skill.getSteps().isBlank() ? "[]" : skill.getSteps(),
                    LIST_MAP_TYPE);
            if ("NEW".equalsIgnoreCase(stepId) || stepsList.stream().noneMatch(
                    s -> stepId.equals(String.valueOf(s.get("id"))))) {
                String newId = "s" + (stepsList.size() + 1) + "_" + Long.toHexString(System.currentTimeMillis());
                Map<String, Object> step = new HashMap<>();
                step.put("id", newId);
                step.put("order", stepsList.size() + 1);
                step.put("text", description);
                step.put("ai_summary", summary);
                step.put("pipeline_id", pipelineId);
                step.put("confirmed", true);
                step.put("pending", false);
                step.put("suggested_actions", List.of());
                step.put("badge", Map.of("kind", "ai", "label", "Pipeline Builder"));
                stepsList.add(step);
            } else {
                for (Map<String, Object> s : stepsList) {
                    if (stepId.equals(String.valueOf(s.get("id")))) {
                        s.put("pipeline_id", pipelineId);
                        if (!description.isBlank()) s.put("text", description);
                        if (!summary.isBlank()) s.put("ai_summary", summary);
                        s.put("pending", false);
                        s.put("confirmed", true);
                        break;
                    }
                }
            }
            skill.setSteps(mapper.writeValueAsString(stepsList));
        } catch (JsonProcessingException e) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "steps_serialization", e.getMessage());
        }
    }
}
