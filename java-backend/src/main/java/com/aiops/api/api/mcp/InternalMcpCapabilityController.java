package com.aiops.api.api.mcp;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * Internal (sidecar-facing) view of the MCP registry (Phase 6). The internal
 * Coordinator agent calls this on turn start to learn which registry
 * capabilities IT admin has granted it (is_internal + coordinator-eligible),
 * then loads them on top of its curated core tools.
 */
@RestController
@RequestMapping("/internal/mcp-capabilities")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalMcpCapabilityController {

    private final McpCapabilityService service;

    public InternalMcpCapabilityController(McpCapabilityService service) {
        this.service = service;
    }

    /** Capabilities granted to the Coordinator. */
    @GetMapping("/agent-tools")
    public ApiResponse<List<McpCapabilityService.Capability>> agentTools() {
        return ApiResponse.ok(service.agentTools());
    }
}
