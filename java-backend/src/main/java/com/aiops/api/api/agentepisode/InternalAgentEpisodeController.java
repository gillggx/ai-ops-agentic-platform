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

    public InternalAgentEpisodeController(AgentEpisodeService service) {
        this.service = service;
    }

    @PostMapping
    public ApiResponse<Map<String, Object>> upsert(@RequestBody Map<String, Object> body) {
        AgentEpisodeEntity ep = service.upsert(
                s(body.get("episode_key")),
                l(body.get("user_id")),
                s(body.get("instruction")),
                s(body.get("started_at")));
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
