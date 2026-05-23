package com.aiops.api.api.skill;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.skill.SkillDocumentEntity;
import com.aiops.api.domain.skill.SkillRunEntity;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.Disposable;

import java.io.IOException;
import java.util.List;
import java.util.Map;

/**
 * Phase 11-A — Skill Document CRUD.
 *
 * <p>After Phase 12 OOP refactor (2026-05-23) this is a thin HTTP layer:
 * binds parameters, calls {@link SkillDocumentService}, wraps responses in
 * {@link ApiResponse} or maps entities through {@link Dtos}. All business
 * logic, validation, sidecar coordination, and entity mutation lives in
 * the service.
 *
 * <p>The SSE {@code /run} endpoint stays here because its body is HTTP-
 * transport plumbing around the reactive {@code Flux<RunnerEvent>} that
 * {@link SkillRunnerService#run} already produces.
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/skill-documents")
public class SkillDocumentController {

    private static final long SSE_TIMEOUT_MS = 5L * 60_000L;

    private final SkillDocumentService service;
    private final SkillRunnerService runner;
    private final ObjectMapper mapper;

    public SkillDocumentController(SkillDocumentService service,
                                   SkillRunnerService runner,
                                   ObjectMapper mapper) {
        this.service = service;
        this.runner = runner;
        this.mapper = mapper;
    }

    // ── Reads ────────────────────────────────────────────────────────────────

    @GetMapping
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<List<Dtos.Summary>> list(@RequestParam(required = false) String stage) {
        return ApiResponse.ok(service.list(stage).stream().map(Dtos::summaryOf).toList());
    }

    @GetMapping("/{slug}")
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<Dtos.Detail> getBySlug(@PathVariable String slug) {
        return ApiResponse.ok(Dtos.detailOf(service.getBySlug(slug)));
    }

    @GetMapping("/{slug}/runs")
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<List<SkillRunEntity>> listRuns(@PathVariable String slug,
                                                       @RequestParam(required = false) Boolean test) {
        return ApiResponse.ok(service.listRuns(slug, test));
    }

    @GetMapping("/{slug}/past-events")
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<List<Map<String, Object>>> pastEvents(@PathVariable String slug) {
        return ApiResponse.ok(service.pastEvents(slug));
    }

    @GetMapping("/{slug}/builder-url")
    @PreAuthorize(Authorities.ADMIN_OR_PE)
    public ApiResponse<Map<String, Object>> builderUrl(@PathVariable String slug,
                                                        @RequestParam String slot,
                                                        @RequestParam(required = false, defaultValue = "") String instruction) {
        return ApiResponse.ok(service.builderUrl(slug, slot, instruction));
    }

    // ── Writes ───────────────────────────────────────────────────────────────

    @PostMapping
    @PreAuthorize(Authorities.ADMIN_OR_PE)
    public ApiResponse<Dtos.Detail> create(@Validated @RequestBody Dtos.CreateRequest req,
                                           @AuthenticationPrincipal AuthPrincipal caller) {
        return ApiResponse.ok(Dtos.detailOf(service.create(req, caller)));
    }

    @PutMapping("/{slug}")
    @PreAuthorize(Authorities.ADMIN_OR_PE)
    public ApiResponse<Dtos.Detail> update(@PathVariable String slug,
                                           @RequestBody Dtos.UpdateRequest req) {
        return ApiResponse.ok(Dtos.detailOf(service.update(slug, req)));
    }

    @DeleteMapping("/{slug}")
    @PreAuthorize(Authorities.ADMIN_OR_PE)
    public ApiResponse<Void> delete(@PathVariable String slug) {
        service.delete(slug);
        return ApiResponse.ok(null);
    }

    @PostMapping("/{slug}/confirm-check")
    @PreAuthorize(Authorities.ADMIN_OR_PE)
    public ApiResponse<Dtos.Detail> setConfirmCheck(@PathVariable String slug,
                                                    @RequestBody Map<String, Object> body,
                                                    @AuthenticationPrincipal AuthPrincipal caller) {
        String text = String.valueOf(body.getOrDefault("text", "")).trim();
        return ApiResponse.ok(Dtos.detailOf(service.setConfirmCheck(slug, text, caller)));
    }

    @DeleteMapping("/{slug}/confirm-check")
    @PreAuthorize(Authorities.ADMIN_OR_PE)
    public ApiResponse<Dtos.Detail> clearConfirmCheck(@PathVariable String slug) {
        return ApiResponse.ok(Dtos.detailOf(service.clearConfirmCheck(slug)));
    }

    @PostMapping("/{slug}/bind-pipeline")
    @PreAuthorize(Authorities.ADMIN_OR_PE)
    public ApiResponse<Dtos.Detail> bindPipeline(@PathVariable String slug,
                                                  @RequestBody Map<String, Object> body) {
        return ApiResponse.ok(Dtos.detailOf(service.bindPipeline(slug, body)));
    }

    @PostMapping("/{slug}/steps")
    @PreAuthorize(Authorities.ADMIN_OR_PE)
    public ApiResponse<Dtos.Detail> addStep(@PathVariable String slug,
                                            @RequestBody Map<String, Object> body,
                                            @AuthenticationPrincipal AuthPrincipal caller) {
        String text = String.valueOf(body.getOrDefault("text", "")).trim();
        return ApiResponse.ok(Dtos.detailOf(service.addStep(slug, text, caller)));
    }

    // ── SSE run (HTTP-transport, stays in controller) ───────────────────────

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
                    } catch (RuntimeException ex) {
                        // Belt-and-suspenders for unexpected runtime errors in
                        // the SSE callback chain; IOException is already caught
                        // above (JsonProcessingException extends it).
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
