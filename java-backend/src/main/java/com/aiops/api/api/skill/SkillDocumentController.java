package com.aiops.api.api.skill;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.skill.SkillDocumentEntity;
import com.aiops.api.domain.skill.SkillDocumentRepository;
import com.aiops.api.domain.skill.SkillRunEntity;
import com.aiops.api.domain.skill.SkillRunRepository;
import jakarta.validation.constraints.NotBlank;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.util.List;
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

    private final SkillDocumentRepository repository;
    private final SkillRunRepository runRepository;

    public SkillDocumentController(SkillDocumentRepository repository,
                                   SkillRunRepository runRepository) {
        this.repository = repository;
        this.runRepository = runRepository;
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
        // TODO 11-A.5: materialize trigger_config + steps into auto_patrols /
        //              pipeline_auto_check_triggers when status flips to stable.
        return ApiResponse.ok(Dtos.detailOf(e));
    }

    @DeleteMapping("/{slug}")
    @PreAuthorize(Authorities.ADMIN_OR_PE)
    @Transactional
    public ApiResponse<Void> delete(@PathVariable String slug) {
        SkillDocumentEntity e = repository.findBySlug(slug)
                .orElseThrow(() -> ApiException.notFound("skill"));
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
}
