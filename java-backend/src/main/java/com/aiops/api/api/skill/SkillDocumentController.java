package com.aiops.api.api.skill;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.skill.PersonalRuleFireRepository;
import com.aiops.api.domain.skill.SkillDocumentEntity;
import com.aiops.api.domain.skill.SkillDocumentRepository;
import com.aiops.api.domain.skill.SkillRunEntity;
import com.aiops.api.domain.skill.SkillRunRepository;
import com.aiops.api.sidecar.PythonSidecarClient;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.constraints.NotBlank;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.Disposable;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * Phase 11-A — Skill Document CRUD.
 *
 * <p>Read-only listing for now (Library page). Write paths (POST/PUT/DELETE)
 * exist as scaffolds; trigger materialization to {@code auto_patrols} /
 * {@code pipeline_auto_check_triggers} is a TODO for 11-A.5 — until then,
 * saved skills exist as documents but don't yet fire on trigger.
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/skill-documents")
public class SkillDocumentController {

    private static final Set<String> VALID_STAGES = Set.of("patrol", "diagnose");
    private static final Set<String> VALID_STATUS = Set.of("draft", "stable");

    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};
    private static final long SSE_TIMEOUT_MS = 5L * 60_000L;

    private final SkillDocumentRepository repository;
    private final SkillRunRepository runRepository;
    private final SkillRunnerService runner;
    private final ObjectMapper mapper;
    private final AlarmRepository alarmRepo;
    private final PersonalRuleFireRepository ruleFireRepo;
    private final PipelineRepository pipelineRepo;
    private final PythonSidecarClient sidecar;
    private final SkillMaterializeService materializer;

    public SkillDocumentController(SkillDocumentRepository repository,
                                   SkillRunRepository runRepository,
                                   SkillRunnerService runner,
                                   ObjectMapper mapper,
                                   AlarmRepository alarmRepo,
                                   PersonalRuleFireRepository ruleFireRepo,
                                   PipelineRepository pipelineRepo,
                                   PythonSidecarClient sidecar,
                                   SkillMaterializeService materializer) {
        this.repository = repository;
        this.runRepository = runRepository;
        this.runner = runner;
        this.mapper = mapper;
        this.alarmRepo = alarmRepo;
        this.ruleFireRepo = ruleFireRepo;
        this.pipelineRepo = pipelineRepo;
        this.sidecar = sidecar;
        this.materializer = materializer;
    }

    /** Library listing — returns the full list, optionally filtered by stage. */
    @GetMapping
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<List<Dtos.Summary>> list(@RequestParam(required = false) String stage) {
        List<SkillDocumentEntity> all = (stage == null || stage.isBlank())
                ? repository.findAll()
                : repository.findByStage(stage);
        List<Dtos.Summary> out = all.stream().map(Dtos::summaryOf).toList();
        return ApiResponse.ok(out);
    }

    /** Get a single skill by slug (Playbook page). */
    @GetMapping("/{slug}")
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<Dtos.Detail> getBySlug(@PathVariable String slug) {
        SkillDocumentEntity e = repository.findBySlug(slug)
                .orElseThrow(() -> ApiException.notFound("skill"));
        return ApiResponse.ok(Dtos.detailOf(e));
    }

    @PostMapping
    @PreAuthorize(Authorities.ADMIN_OR_PE)
    @Transactional
    public ApiResponse<Dtos.Detail> create(@Validated @RequestBody Dtos.CreateRequest req,
                                           @AuthenticationPrincipal AuthPrincipal caller) {
        if (!VALID_STAGES.contains(req.stage())) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "validation_error", "stage must be patrol|diagnose");
        }
        if (repository.existsBySlug(req.slug())) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "duplicate_slug", "slug already exists: " + req.slug());
        }
        SkillDocumentEntity e = new SkillDocumentEntity();
        e.setSlug(req.slug());
        e.setTitle(req.title());
        e.setStage(req.stage());
        e.setDomain(Objects.requireNonNullElse(req.domain(), ""));
        e.setDescription(Objects.requireNonNullElse(req.description(), ""));
        e.setAuthorUserId(caller != null ? caller.userId() : null);
        e.setVersion(Objects.requireNonNullElse(req.version(), "0.1"));
        e.setStatus("draft");
        e.setTriggerConfig(Objects.requireNonNullElse(req.triggerConfig(), "{}"));
        e.setSteps(Objects.requireNonNullElse(req.steps(), "[]"));
        SkillDocumentEntity saved = repository.save(e);
        log.info("skill created: id={} slug={} author={}", saved.getId(), saved.getSlug(),
                e.getAuthorUserId());
        return ApiResponse.ok(Dtos.detailOf(saved));
    }

    @PutMapping("/{slug}")
    @PreAuthorize(Authorities.ADMIN_OR_PE)
    @Transactional
    public ApiResponse<Dtos.Detail> update(@PathVariable String slug,
                                           @RequestBody Dtos.UpdateRequest req) {
        SkillDocumentEntity e = repository.findBySlug(slug)
                .orElseThrow(() -> ApiException.notFound("skill"));
        if (req.title() != null) e.setTitle(req.title());
        if (req.stage() != null) {
            if (!VALID_STAGES.contains(req.stage())) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "validation_error", "stage must be patrol|diagnose");
            }
            e.setStage(req.stage());
        }
        String oldStatus = e.getStatus();
        if (req.status() != null) {
            if (!VALID_STATUS.contains(req.status())) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "validation_error", "status must be draft|stable");
            }
            e.setStatus(req.status());
        }
        if (req.domain() != null) e.setDomain(req.domain());
        if (req.description() != null) e.setDescription(req.description());
        if (req.certifiedBy() != null) e.setCertifiedBy(req.certifiedBy());
        if (req.version() != null) e.setVersion(req.version());
        if (req.triggerConfig() != null) e.setTriggerConfig(req.triggerConfig());
        if (req.steps() != null) e.setSteps(req.steps());

        // Phase 11 — materialize / clear trigger rows on status transitions.
        String newStatus = e.getStatus();
        if (!java.util.Objects.equals(oldStatus, newStatus)) {
            if ("stable".equals(newStatus)) {
                int n = materializer.materialize(e);
                log.info("skill {} published (stable) — materialized {} rows", e.getSlug(), n);
            } else if ("draft".equals(newStatus) && "stable".equals(oldStatus)) {
                int n = materializer.clear(e);
                log.info("skill {} unpublished (draft) — cleared {} rows", e.getSlug(), n);
            }
        } else if ("stable".equals(newStatus) && (req.triggerConfig() != null || req.steps() != null)) {
            // Already published and trigger/steps changed → re-materialize.
            int n = materializer.materialize(e);
            log.info("skill {} re-materialized {} rows after stable-edit", e.getSlug(), n);
        }
        return ApiResponse.ok(Dtos.detailOf(e));
    }

    @DeleteMapping("/{slug}")
    @PreAuthorize(Authorities.ADMIN_OR_PE)
    @Transactional
    public ApiResponse<Void> delete(@PathVariable String slug) {
        SkillDocumentEntity e = repository.findBySlug(slug)
                .orElseThrow(() -> ApiException.notFound("skill"));
        // Clear materialized trigger rows first so we don't leave dangling
        // auto_patrols / auto_check rows pointing at a deleted skill.
        materializer.clear(e);
        repository.delete(e);
        return ApiResponse.ok(null);
    }

    @GetMapping("/{slug}/runs")
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<List<SkillRunEntity>> listRuns(@PathVariable String slug,
                                                       @RequestParam(required = false) Boolean test) {
        SkillDocumentEntity e = repository.findBySlug(slug)
                .orElseThrow(() -> ApiException.notFound("skill"));
        List<SkillRunEntity> runs = (test == null)
                ? runRepository.findBySkillIdOrderByTriggeredAtDesc(e.getId())
                : runRepository.findBySkillIdAndIsTestOrderByTriggeredAtDesc(e.getId(), test);
        return ApiResponse.ok(runs);
    }

    /**
     * Phase 11 — translate a NL step description into a pipeline (ending in
     * block_step_check), persist it as a new pb_pipelines row, and append
     * the step into skill.steps[].
     *
     * <p>Body: {"text": "..."}
     * <p>Response: updated SkillDetail with the new step appended.
     */
    @PostMapping("/{slug}/steps")
    @PreAuthorize(Authorities.ADMIN_OR_PE)
    @Transactional
    public ApiResponse<Dtos.Detail> addStep(@PathVariable String slug,
                                            @RequestBody Map<String, Object> body,
                                            @AuthenticationPrincipal AuthPrincipal caller) {
        String text = String.valueOf(body.getOrDefault("text", "")).trim();
        if (text.isBlank()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "validation_error", "text required");
        }
        SkillDocumentEntity skill = repository.findBySlug(slug)
                .orElseThrow(() -> ApiException.notFound("skill"));

        // Call sidecar /internal/agent/skill/translate-step (block on Mono).
        Map<String, Object> req = Map.of("text", text);
        @SuppressWarnings({"unchecked", "rawtypes"})
        Map result;
        try {
            result = sidecar.postJson("/internal/agent/skill/translate-step", req, Map.class, caller)
                    .block(java.time.Duration.ofMinutes(2));
        } catch (Exception ex) {
            log.warn("skill translate-step failed: {}", ex.toString());
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "translate_failed",
                    "sidecar unavailable: " + ex.getMessage());
        }
        if (result == null) {
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "translate_failed",
                    "sidecar returned null");
        }
        String resStatus = String.valueOf(result.getOrDefault("status", ""));
        Object pj = result.get("pipeline_json");
        String summary = String.valueOf(result.getOrDefault("summary", ""));
        if (!"finished".equals(resStatus) || !(pj instanceof Map)) {
            // Save step with null pipeline_id so user can iterate; surface error in ai_summary.
            String err = String.valueOf(result.getOrDefault("error_message", "translation incomplete"));
            return appendStep(skill, text, null, "(translation 失敗) " + err);
        }

        // Persist the new pipeline as a pb_pipelines row.
        PipelineEntity pe = new PipelineEntity();
        pe.setName("[Skill] " + skill.getTitle() + " · step");
        pe.setDescription(text);
        pe.setStatus("draft");
        pe.setPipelineKind("diagnostic");
        try {
            pe.setPipelineJson(mapper.writeValueAsString(pj));
        } catch (Exception e) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "pipeline_save_failed", e.getMessage());
        }
        pe.setCreatedBy(caller != null ? caller.userId() : null);
        PipelineEntity saved = pipelineRepo.save(pe);

        return appendStep(skill, text, saved.getId(), summary);
    }

    @SuppressWarnings("unchecked")
    private ApiResponse<Dtos.Detail> appendStep(SkillDocumentEntity skill, String text,
                                                 Long pipelineId, String aiSummary) {
        try {
            List<Map<String, Object>> stepsList = mapper.readValue(
                    skill.getSteps() == null || skill.getSteps().isBlank() ? "[]" : skill.getSteps(),
                    new TypeReference<List<Map<String, Object>>>() {});
            String newId = "s" + (stepsList.size() + 1) + "_" + Long.toHexString(System.currentTimeMillis());
            Map<String, Object> step = new java.util.HashMap<>();
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
            return ApiResponse.ok(Dtos.detailOf(skill));
        } catch (Exception e) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "steps_serialization", e.getMessage());
        }
    }

    /**
     * Phase 11 — Past-event replay sources for the Test modal's "From past
     * event" tab. Returns up to 30 historical trigger payloads matching the
     * skill's trigger_config.
     *
     * - trigger.type=system   → alarms WHERE trigger_event = event_type
     * - trigger.type=user     → personal_rule_fires for the materialized rule
     * - trigger.type=schedule → past skill_runs for this skill (excluding tests)
     */
    @GetMapping("/{slug}/past-events")
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<List<Map<String, Object>>> pastEvents(@PathVariable String slug) {
        SkillDocumentEntity skill = repository.findBySlug(slug)
                .orElseThrow(() -> ApiException.notFound("skill"));
        Map<String, Object> trig = parseJson(skill.getTriggerConfig());
        String type = String.valueOf(trig.getOrDefault("type", "schedule"));
        List<Map<String, Object>> out = new java.util.ArrayList<>();

        if ("system".equals(type)) {
            String eventType = String.valueOf(trig.getOrDefault("event_type", ""));
            if (!eventType.isBlank()) {
                List<AlarmEntity> alarms = alarmRepo.findTop30ByTriggerEventOrderByCreatedAtDesc(eventType);
                for (AlarmEntity a : alarms) {
                    Map<String, Object> tc = new java.util.HashMap<>();
                    tc.put("id", "hc-" + a.getId());
                    tc.put("kind", "historical");
                    tc.put("title", a.getTitle() != null && !a.getTitle().isBlank() ? a.getTitle() : eventType);
                    tc.put("desc", "Past " + eventType + " on " + a.getEquipmentId());
                    Map<String, Object> meta = new java.util.HashMap<>();
                    meta.put("tool", a.getEquipmentId());
                    meta.put("lot", a.getLotId());
                    meta.put("time", a.getEventTime() != null ? a.getEventTime().toString() : null);
                    meta.put("outcome", a.getStatus());
                    tc.put("meta", meta);
                    Map<String, Object> payload = new java.util.HashMap<>();
                    payload.put("event_type", eventType);
                    payload.put("alarm_id", a.getId());
                    payload.put("tool_id", a.getEquipmentId());
                    payload.put("lot_id", a.getLotId());
                    payload.put("severity", a.getSeverity());
                    payload.put("event_time", a.getEventTime() != null ? a.getEventTime().toString() : null);
                    tc.put("payload", payload);
                    out.add(tc);
                }
            }
        } else if ("user".equals(type)) {
            // user-defined rule fires are tied to a materialized auto_patrol row.
            // Materialization is in this same commit; if not yet materialized, list is empty.
            // We look up the auto_patrol that has skill_doc_id = skill.id and trigger_mode='event'/'schedule'.
            // For now, return empty + a synthetic "fill manually" hint.
        } else {
            // schedule: surface past skill_runs (excluding tests) as replay sources
            List<SkillRunEntity> runs = runRepository.findBySkillIdAndIsTestOrderByTriggeredAtDesc(skill.getId(), false);
            int n = Math.min(runs.size(), 30);
            for (int i = 0; i < n; i++) {
                SkillRunEntity r = runs.get(i);
                Map<String, Object> tc = new java.util.HashMap<>();
                tc.put("id", "sr-" + r.getId());
                tc.put("kind", "historical");
                tc.put("title", "Past run #" + r.getId());
                tc.put("desc", "Run at " + r.getTriggeredAt());
                Map<String, Object> meta = new java.util.HashMap<>();
                meta.put("time", r.getTriggeredAt() != null ? r.getTriggeredAt().toString() : null);
                meta.put("outcome", r.getStatus());
                tc.put("meta", meta);
                tc.put("payload", parseJson(r.getTriggerPayload()));
                out.add(tc);
            }
        }

        return ApiResponse.ok(out);
    }

    private Map<String, Object> parseJson(String json) {
        if (json == null || json.isBlank()) return Map.of();
        try {
            return mapper.readValue(json, MAP_TYPE);
        } catch (Exception e) {
            return Map.of();
        }
    }

    /**
     * Run the skill end-to-end (all steps in order). SSE stream emits
     * step_start / step_done / done events.
     *
     * <p>Body: {"trigger_payload": {...}, "is_test": bool}
     * <p>is_test=true marks the run as sandbox (no notification, excluded from
     * stats); used by the Test modal in the frontend.
     */
    @PostMapping(path = "/{slug}/run", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    @PreAuthorize(Authorities.ADMIN_OR_PE)
    public SseEmitter run(@PathVariable String slug,
                          @RequestBody Map<String, Object> body,
                          @AuthenticationPrincipal AuthPrincipal caller) {
        @SuppressWarnings("unchecked")
        Map<String, Object> payload = body.get("trigger_payload") instanceof Map<?, ?> p
                ? (Map<String, Object>) p : Map.of();
        boolean isTest = Boolean.TRUE.equals(body.get("is_test"));

        SseEmitter emitter = new SseEmitter(SSE_TIMEOUT_MS);
        Disposable subscription = runner.run(slug, payload, isTest, caller).subscribe(
                ev -> {
                    try {
                        emitter.send(SseEmitter.event()
                                .name(ev.type())
                                .data(mapper.writeValueAsString(ev.data())));
                    } catch (IOException ioe) {
                        log.debug("SSE client gone on skill {}: {}", slug, ioe.getMessage());
                        emitter.completeWithError(ioe);
                    } catch (Exception ex) {
                        log.warn("SSE serialization failed: {}", ex.toString());
                    }
                },
                err -> {
                    log.warn("SkillRunner error on {}: {}", slug, err.toString());
                    emitter.completeWithError(err);
                },
                emitter::complete
        );
        emitter.onTimeout(subscription::dispose);
        emitter.onError(e -> subscription.dispose());
        emitter.onCompletion(subscription::dispose);
        return emitter;
    }
}
