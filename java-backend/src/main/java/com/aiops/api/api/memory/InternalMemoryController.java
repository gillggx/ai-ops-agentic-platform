package com.aiops.api.api.memory;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * Internal memory-layer write endpoints for the sidecar MemoryWriter
 * (V70; spec MULTI_AGENT_MEMORY_SPEC §3.2). Thin: bind → delegate → echo.
 */
@RestController
@RequestMapping("/internal/memory")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalMemoryController {

    private final MemoryWriteService service;

    public InternalMemoryController(MemoryWriteService service) {
        this.service = service;
    }

    @PostMapping("/knowledge")
    public ApiResponse<Map<String, Object>> createKnowledge(@RequestBody Map<String, Object> body) {
        return ApiResponse.ok(service.createKnowledge(
                asLong(body.get("user_id")),
                s(body.get("memo_class")),
                s(body.get("title")),
                s(body.get("body")),
                s(body.get("applies_to")),
                s(body.get("source")),
                body.get("active") == null ? null : Boolean.valueOf(String.valueOf(body.get("active"))),
                s(body.get("written_by"))));
    }

    @PostMapping("/doc-memos")
    public ApiResponse<Map<String, Object>> createDocMemo(@RequestBody Map<String, Object> body) {
        return ApiResponse.ok(service.createDocMemo(
                s(body.get("block_id")),
                s(body.get("param")),
                s(body.get("memo")),
                s(body.get("verdict_context")),
                s(body.get("from_episode"))));
    }

    private static String s(Object o) {
        return o == null ? null : String.valueOf(o);
    }

    private static Long asLong(Object o) {
        if (o == null) return null;
        if (o instanceof Number n) return n.longValue();
        try {
            return Long.parseLong(String.valueOf(o));
        } catch (NumberFormatException ex) {
            return null;
        }
    }
}
