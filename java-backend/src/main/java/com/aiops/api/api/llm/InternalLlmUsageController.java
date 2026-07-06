package com.aiops.api.api.llm;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * Internal LLM usage rollup write endpoint (S3, V75). The sidecar's
 * llm_client fires one increment per completed LLM call; the row is
 * upserted atomically (see {@code LlmProviderDailyRepository}).
 */
@RestController
@RequestMapping("/internal/llm-usage")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalLlmUsageController {

    private final LlmUsageService service;

    public InternalLlmUsageController(LlmUsageService service) {
        this.service = service;
    }

    @PostMapping("/increment")
    public ApiResponse<Map<String, Object>> increment(@RequestBody Map<String, Object> body) {
        return ApiResponse.ok(service.increment(
                body.get("model") == null ? null : String.valueOf(body.get("model")),
                asBool(body.get("empty")),
                asBool(body.get("error")),
                asLong(body.get("input_tokens")),
                asLong(body.get("output_tokens")),
                asLong(body.get("cache_read"))));
    }

    private static boolean asBool(Object o) {
        if (o instanceof Boolean b) return b;
        return o != null && Boolean.parseBoolean(String.valueOf(o));
    }

    private static long asLong(Object o) {
        if (o == null) return 0L;
        if (o instanceof Number n) return n.longValue();
        try {
            return Long.parseLong(String.valueOf(o));
        } catch (NumberFormatException ex) {
            return 0L;
        }
    }
}
