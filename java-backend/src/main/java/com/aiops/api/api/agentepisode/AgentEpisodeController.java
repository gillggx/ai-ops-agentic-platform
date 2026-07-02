package com.aiops.api.api.agentepisode;

import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.agentepisode.AgentEpisodeEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * User-facing feedback intake (spec §4.4 / Step 6). The three-button strip on
 * the build-result card posts here: sentiment ∈ accept|edit|reject (+ optional
 * text). Divergence (self-ok BUT user-reject) is derived in the service — this
 * is the raw signal for the Supervisor loop and, in later phases, the
 * Repair post_delivery trigger. Recording only: NO automatic behaviour fires.
 */
@RestController
@RequestMapping("/api/v1/agent-episodes")
public class AgentEpisodeController {

    private final AgentEpisodeService service;

    public AgentEpisodeController(AgentEpisodeService service) {
        this.service = service;
    }

    @PostMapping("/{key}/feedback")
    @PreAuthorize(Authorities.ANY_ROLE)
    public ApiResponse<Map<String, Object>> feedback(@PathVariable("key") String key,
                                                     @RequestBody Map<String, Object> body) {
        AgentEpisodeEntity ep = service.appendFeedback(key,
                body.get("stage") == null ? "delivery" : String.valueOf(body.get("stage")),
                body.get("sentiment") == null ? null : String.valueOf(body.get("sentiment")),
                body.get("text") == null ? null : String.valueOf(body.get("text")));
        return ApiResponse.ok(Map.of("id", ep.getId(), "divergence", ep.isDivergence()));
    }
}
