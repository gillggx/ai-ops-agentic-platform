package com.aiops.api.api.handoff;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.handoff.UiHandoffEntity;
import org.springframework.http.MediaType;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * User-facing UI-handoff API (V63). The authenticated human reviews a handoff
 * and resolves it — and {@link HandoffService#resolve} is the ONLY place the
 * dangerous mutation (delete/disable/activate a rule) actually runs.
 *
 * <p>{@code /stream} is the SSE channel an already-open app subscribes to so a
 * fresh handoff auto-surfaces (the "B" path); the cowork link is the fallback.
 */
@RestController
@RequestMapping("/api/v1/handoffs")
public class HandoffController {

    private final HandoffService service;

    public HandoffController(HandoffService service) {
        this.service = service;
    }

    @GetMapping("/{id}")
    @PreAuthorize(Authorities.ADMIN_OR_PE)
    public ApiResponse<Dto> get(@PathVariable String id) {
        return ApiResponse.ok(Dto.of(service.get(id)));
    }

    @PostMapping("/{id}/resolve")
    @PreAuthorize(Authorities.ADMIN_OR_PE)
    public ApiResponse<Dto> resolve(@PathVariable String id,
                                    @AuthenticationPrincipal AuthPrincipal caller) {
        return ApiResponse.ok(Dto.of(service.resolve(id, caller == null ? null : caller.userId())));
    }

    @PostMapping("/{id}/cancel")
    @PreAuthorize(Authorities.ADMIN_OR_PE)
    public ApiResponse<Dto> cancel(@PathVariable String id,
                                   @AuthenticationPrincipal AuthPrincipal caller) {
        return ApiResponse.ok(Dto.of(service.cancel(id, caller == null ? null : caller.userId())));
    }

    @GetMapping(path = "/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    @PreAuthorize(Authorities.ADMIN_OR_PE)
    public SseEmitter stream() {
        return service.subscribe();
    }

    /** Wire DTO — Jackson emits snake_case (target_ref, expires_at, ...). */
    public record Dto(String id, String kind, String targetRef, String action,
                      String payload, String status, String expiresAt) {
        static Dto of(UiHandoffEntity h) {
            return new Dto(h.getId(), h.getKind(), h.getTargetRef(), h.getAction(),
                    h.getPayload(), h.getStatus(),
                    h.getExpiresAt() == null ? null : h.getExpiresAt().toString());
        }
    }
}
