package com.aiops.api.api.handoff;

import com.aiops.api.api.skill.SkillDocumentService;
import com.aiops.api.common.ApiException;
import com.aiops.api.domain.handoff.UiHandoffEntity;
import com.aiops.api.domain.handoff.UiHandoffRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.security.SecureRandom;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * UI handoff service (V63) — "cowork proposes, the human disposes in the GUI".
 *
 * <p>Creates short-lived handoff records (called by the MCP server via the
 * internal controller) and resolves them (called by the authenticated UI). The
 * dangerous mutations (delete / disable / activate a skill-document rule) run
 * HERE on {@link #resolve}, under the resolving user — the MCP layer never
 * executes them.
 *
 * <p>Also keeps a live {@link SseEmitter} registry so an already-open app can
 * auto-surface a new handoff (the "B" auto-popup path); when no client is
 * connected the cowork-provided link is the fallback ("A").
 */
@Slf4j
@Service
public class HandoffService {

    static final Set<String> KINDS = Set.of(
            "review_rule", "confirm_delete", "confirm_disable", "confirm_activate", "view_detail");
    private static final long TTL_MINUTES = 15;
    private static final char[] HEX = "0123456789abcdef".toCharArray();
    private static final SecureRandom RNG = new SecureRandom();

    private final UiHandoffRepository repo;
    private final SkillDocumentService skills;
    private final List<SseEmitter> emitters = new CopyOnWriteArrayList<>();

    public HandoffService(UiHandoffRepository repo, SkillDocumentService skills) {
        this.repo = repo;
        this.skills = skills;
    }

    private static String newId() {
        byte[] b = new byte[12];
        RNG.nextBytes(b);
        StringBuilder sb = new StringBuilder("ho_");
        for (byte x : b) {
            sb.append(HEX[(x >> 4) & 0xF]).append(HEX[x & 0xF]);
        }
        return sb.toString();
    }

    // ── Create (called by MCP via /internal) ───────────────────────────────
    @Transactional
    public UiHandoffEntity create(String kind, String targetRef, String action,
                                  String payload, String requestedBy) {
        if (!KINDS.contains(kind)) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "validation_error",
                    "kind must be one of " + KINDS);
        }
        UiHandoffEntity h = new UiHandoffEntity();
        h.setId(newId());
        h.setKind(kind);
        h.setTargetRef(targetRef);
        h.setAction(action);
        h.setPayload(payload);
        h.setStatus("pending");
        h.setRequestedBy(requestedBy != null ? requestedBy : "cowork");
        h.setExpiresAt(OffsetDateTime.now().plusMinutes(TTL_MINUTES));
        UiHandoffEntity saved = repo.save(h);
        publish(saved);
        return saved;
    }

    // ── Read ────────────────────────────────────────────────────────────────
    public UiHandoffEntity get(String id) {
        UiHandoffEntity h = repo.findById(id).orElseThrow(() -> ApiException.notFound("handoff"));
        return expireIfStale(h);
    }

    private UiHandoffEntity expireIfStale(UiHandoffEntity h) {
        if ("pending".equals(h.getStatus()) && h.getExpiresAt().isBefore(OffsetDateTime.now())) {
            h.setStatus("expired");
            repo.save(h);
        }
        return h;
    }

    // ── Resolve (called by the authenticated UI) — executes the action ──────
    @Transactional
    public UiHandoffEntity resolve(String id, Long userId) {
        UiHandoffEntity h = get(id);
        if (!"pending".equals(h.getStatus())) {
            throw new ApiException(HttpStatus.GONE, "handoff_" + h.getStatus(),
                    "handoff is " + h.getStatus() + " and can no longer be resolved");
        }
        switch (h.getKind()) {
            case "confirm_delete" -> skills.delete(h.getTargetRef());
            case "confirm_disable" -> skills.setStatus(h.getTargetRef(), "draft");
            case "confirm_activate" -> skills.setStatus(h.getTargetRef(), "stable");
            case "review_rule", "view_detail" -> { /* no mutation — just mark reviewed */ }
            default -> throw new ApiException(HttpStatus.BAD_REQUEST, "validation_error",
                    "unknown handoff kind " + h.getKind());
        }
        h.setStatus("resolved");
        h.setResolvedBy(userId);
        h.setResolvedAt(OffsetDateTime.now());
        return repo.save(h);
    }

    @Transactional
    public UiHandoffEntity cancel(String id, Long userId) {
        UiHandoffEntity h = get(id);
        if ("pending".equals(h.getStatus())) {
            h.setStatus("cancelled");
            h.setResolvedBy(userId);
            h.setResolvedAt(OffsetDateTime.now());
            repo.save(h);
        }
        return h;
    }

    // ── SSE registry (B: auto-popup for already-open apps) ──────────────────
    public SseEmitter subscribe() {
        SseEmitter emitter = new SseEmitter(0L); // no timeout — long-lived
        emitters.add(emitter);
        emitter.onCompletion(() -> emitters.remove(emitter));
        emitter.onTimeout(() -> emitters.remove(emitter));
        emitter.onError(e -> emitters.remove(emitter));
        try {
            emitter.send(SseEmitter.event().name("hello").data("{\"ok\":true}"));
        } catch (IOException e) {
            emitters.remove(emitter);
        }
        return emitter;
    }

    private void publish(UiHandoffEntity h) {
        String json = "{\"id\":\"" + h.getId() + "\",\"kind\":\"" + h.getKind()
                + "\",\"target_ref\":" + (h.getTargetRef() == null ? "null" : "\"" + h.getTargetRef() + "\"")
                + ",\"action\":" + (h.getAction() == null ? "null" : "\"" + h.getAction() + "\"") + "}";
        for (SseEmitter e : emitters) {
            try {
                e.send(SseEmitter.event().name("handoff").data(json));
            } catch (IOException | RuntimeException ex) {
                emitters.remove(e);
            }
        }
    }
}
