package com.aiops.api.api.handoff;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.handoff.UiHandoffEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * Internal endpoint the MCP server calls to create a UI handoff (V63).
 * The MCP layer holds NO execute power — it only creates the handoff and shows
 * the user the returned launch link; the dangerous mutation runs later from the
 * authenticated UI via {@link HandoffController#resolve}.
 */
@RestController
@RequestMapping("/internal/handoffs")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalHandoffController {

    private final HandoffService service;

    public InternalHandoffController(HandoffService service) {
        this.service = service;
    }

    @PostMapping
    public ApiResponse<Map<String, Object>> create(@RequestBody Map<String, Object> body) {
        String kind = String.valueOf(body.getOrDefault("kind", "")).trim();
        String targetRef = body.get("target_ref") == null ? null : String.valueOf(body.get("target_ref"));
        String action = body.get("action") == null ? null : String.valueOf(body.get("action"));
        Object payloadObj = body.get("payload");
        String payload = payloadObj == null ? null
                : (payloadObj instanceof String s ? s : payloadObj.toString());
        String requestedBy = body.get("requested_by") == null ? null : String.valueOf(body.get("requested_by"));

        UiHandoffEntity h = service.create(kind, targetRef, action, payload, requestedBy);
        return ApiResponse.ok(Map.of(
                "id", h.getId(),
                "kind", h.getKind(),
                "expires_at", h.getExpiresAt().toString()));
    }
}
