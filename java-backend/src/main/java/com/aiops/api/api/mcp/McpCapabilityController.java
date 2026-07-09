package com.aiops.api.api.mcp;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * MCP capability registry — IT-admin catalog + exposure control (Phase 2/3).
 * Thin controller: bind + delegate. Lists every capability (built-in tools +
 * domain skills + external MCPs) with its public/private and write flag; lets
 * IT admin flip a capability's public/private. Reads are ADMIN-only since this
 * governs what cowork can reach.
 */
@RestController
@RequestMapping("/api/v1/mcp-capabilities")
@PreAuthorize(Authorities.ADMIN)
public class McpCapabilityController {

    private final McpCapabilityService service;

    public McpCapabilityController(McpCapabilityService service) {
        this.service = service;
    }

    /** Full catalog for the admin page. */
    @GetMapping
    public ApiResponse<List<McpCapabilityService.Capability>> catalog() {
        return ApiResponse.ok(service.catalog());
    }

    /** Flip one capability's public/private. Body (snake_case wire):
     *  {@code {"kind": "...", "is_public": true|false}}. */
    @PutMapping("/{key}/exposure")
    public ApiResponse<McpCapabilityService.Capability> setExposure(
            @PathVariable("key") String key,
            @RequestBody Map<String, Object> body,
            @AuthenticationPrincipal AuthPrincipal caller) {
        String kind = String.valueOf(body.getOrDefault("kind", "builtin"));
        boolean isPublic = Boolean.TRUE.equals(body.get("is_public"));
        String who = caller != null && caller.username() != null ? caller.username() : "admin";
        return ApiResponse.ok(service.setExposure(key, kind, isPublic, who));
    }
}
