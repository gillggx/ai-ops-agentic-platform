package com.aiops.api.api.agentepisode;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.agentepisode.AgentEpisodeEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * Internal write path for the sidecar's EpisodeRecorder (V69).
 *
 * <p>The recorder is fire-and-forget + fail-open: it batches behavioural
 * events in memory and flushes at phase boundaries / finalize. These
 * endpoints therefore stay dumb — bind, delegate, echo — and the service
 * absorbs out-of-order arrivals (stub episode on unknown key).
 */
@RestController
@RequestMapping("/internal/agent-episodes")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalAgentEpisodeController {

    private final AgentEpisodeService service;
    private final SupervisorReportService reports;
    private final AgentActivityService activity;

    public InternalAgentEpisodeController(AgentEpisodeService service,
                                          SupervisorReportService reports,
                                          AgentActivityService activity) {
        this.service = service;
        this.reports = reports;
        this.activity = activity;
    }

    // ── Read path (2026-07-08, cowork requirement #1) — 唯讀觀測，供外部
    // Claude (MCP) 查建置軌跡；與 /api/v1/agent-activity 同一個 service。 ──

    @GetMapping
    public ApiResponse<List<Map<String, Object>>> list(
            @RequestParam(name = "limit", defaultValue = "20") int limit) {
        return ApiResponse.ok(activity.list(Math.min(Math.max(limit, 1), 100)));
    }

    @GetMapping("/{key}")
    public ApiResponse<Map<String, Object>> detail(@PathVariable("key") String key) {
        return ApiResponse.ok(activity.detail(key));
    }

    @GetMapping("/{key}/rounds")
    public ApiResponse<Map<String, Object>> rounds(@PathVariable("key") String key) {
        return ApiResponse.ok(activity.rounds(key));
    }

    /** Supervisor v1 aggregates (spec §5) — read-only, report material. */
    @GetMapping("/report")
    public ApiResponse<Map<String, Object>> report(
            @RequestParam(name = "days", defaultValue = "30") int days) {
        return ApiResponse.ok(reports.report(Math.max(1, Math.min(days, 365))));
    }

    @PostMapping
    public ApiResponse<Map<String, Object>> upsert(@RequestBody Map<String, Object> body) {
        AgentEpisodeEntity ep = service.upsert(
                s(body.get("episode_key")),
                l(body.get("user_id")),
                s(body.get("instruction")),
                s(body.get("started_at")),
                s(body.get("trigger_source")));
        return ApiResponse.ok(Map.of("id", ep.getId(), "episode_key", ep.getEpisodeKey()));
    }

    @PostMapping("/{key}/steps")
    public ApiResponse<Map<String, Object>> appendSteps(@PathVariable("key") String key,
                                                        @RequestBody Map<String, Object> body) {
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> batch = (List<Map<String, Object>>) body.get("steps");
        int written = service.appendSteps(key, batch);
        return ApiResponse.ok(Map.of("written", written));
    }

    @PostMapping("/{key}/finalize")
    public ApiResponse<Map<String, Object>> finalizeEpisode(@PathVariable("key") String key,
                                                            @RequestBody Map<String, Object> body) {
        AgentEpisodeEntity ep = service.finalizeEpisode(key, body);
        return ApiResponse.ok(Map.of(
                "id", ep.getId(), "status", ep.getStatus(), "divergence", ep.isDivergence()));
    }

    @PostMapping("/{key}/feedback")
    public ApiResponse<Map<String, Object>> feedback(@PathVariable("key") String key,
                                                     @RequestBody Map<String, Object> body) {
        AgentEpisodeEntity ep = service.appendFeedback(key,
                s(body.get("stage")), s(body.get("sentiment")), s(body.get("text")));
        return ApiResponse.ok(Map.of("id", ep.getId(), "divergence", ep.isDivergence()));
    }

    private static String s(Object o) {
        return o == null ? null : String.valueOf(o);
    }

    private static Long l(Object o) {
        if (o == null) return null;
        if (o instanceof Number n) return n.longValue();
        try {
            return Long.parseLong(String.valueOf(o));
        } catch (NumberFormatException ex) {
            return null;
        }
    }
}
