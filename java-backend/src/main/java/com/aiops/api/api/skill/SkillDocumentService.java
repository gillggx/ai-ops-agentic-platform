package com.aiops.api.api.skill;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.common.ApiException;
import com.aiops.api.domain.skill.SkillDocumentEntity;
import com.aiops.api.domain.skill.SkillDocumentRepository;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

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
 * all entity manipulation, validation, JSON serdes, and cross-entity
 * coordination lives here.
 *
 * <p>Methods raise {@link ApiException} for client-facing errors; runtime
 * errors leak as RuntimeException so {@code @ControllerAdvice} can map
 * them to 500 with stack preserved (no silent swallow).
 */
@Slf4j
@Service
public class SkillDocumentService {

    static final Set<String> VALID_STAGES = Set.of("patrol", "diagnose");
    static final Set<String> VALID_STATUS = Set.of("draft", "stable");
    static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final SkillDocumentRepository repository;
    private final ObjectMapper mapper;

    public SkillDocumentService(SkillDocumentRepository repository, ObjectMapper mapper) {
        this.repository = repository;
        this.mapper = mapper;
    }

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
        } catch (Exception ex) {
            // Bad JSON in trigger_config → can't derive; let caller fall back.
            log.debug("stageFromTrigger: parse failed for trigger_config — {}", ex.toString());
            return null;
        }
    }
}
