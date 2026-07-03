package com.aiops.api.api.agentepisode;

import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * Agent Activity read API (spec MULTI_AGENT_ACTIVITY_UI_SPEC §3). User-facing
 * (ADMIN_OR_PE) — the /agent-activity page proxies here. Read-only.
 */
@RestController
@RequestMapping("/api/v1/agent-activity")
@PreAuthorize(Authorities.ADMIN_OR_PE)
public class AgentActivityController {

    private final AgentActivityService activity;
    private final SupervisorReportService reports;

    public AgentActivityController(AgentActivityService activity,
                                   SupervisorReportService reports) {
        this.activity = activity;
        this.reports = reports;
    }

    @GetMapping("/episodes")
    public ApiResponse<List<Map<String, Object>>> episodes(
            @RequestParam(name = "limit", defaultValue = "30") int limit) {
        return ApiResponse.ok(activity.list(limit));
    }

    @GetMapping("/episodes/{key}")
    public ApiResponse<Map<String, Object>> episode(@PathVariable("key") String key) {
        return ApiResponse.ok(activity.detail(key));
    }

    @GetMapping("/episodes/{key}/rounds")
    public ApiResponse<Map<String, Object>> rounds(@PathVariable("key") String key) {
        return ApiResponse.ok(activity.rounds(key));
    }

    @GetMapping("/report")
    public ApiResponse<Map<String, Object>> report(
            @RequestParam(name = "days", defaultValue = "30") int days) {
        return ApiResponse.ok(reports.report(Math.max(1, Math.min(days, 365))));
    }
}
