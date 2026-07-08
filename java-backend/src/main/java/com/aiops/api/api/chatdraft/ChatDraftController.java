package com.aiops.api.api.chatdraft;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * Chat 草稿暫存區 (V78, 2026-07-08). Per-user shelf of the most-recent 10
 * chat-built pipelines. Thin controller — bind + delegate; the service owns
 * eviction + serdes.
 */
@RestController
@RequestMapping("/api/v1/chat-drafts")
@PreAuthorize(Authorities.ANY_ROLE)
public class ChatDraftController {

    private final ChatDraftService service;

    public ChatDraftController(ChatDraftService service) {
        this.service = service;
    }

    @GetMapping
    public ApiResponse<Map<String, Object>> list(@AuthenticationPrincipal AuthPrincipal caller) {
        return ApiResponse.ok(service.list(caller.userId()));
    }

    @GetMapping("/{id}")
    public ApiResponse<Map<String, Object>> get(@PathVariable("id") Long id,
                                                @AuthenticationPrincipal AuthPrincipal caller) {
        return ApiResponse.ok(service.get(id, caller.userId()));
    }

    @PostMapping
    public ApiResponse<Map<String, Object>> create(@RequestBody Map<String, Object> body,
                                                   @AuthenticationPrincipal AuthPrincipal caller) {
        return ApiResponse.ok(service.create(caller.userId(), body));
    }

    @PatchMapping("/{id}/mark")
    public ApiResponse<Map<String, Object>> mark(@PathVariable("id") Long id,
                                                 @RequestBody Map<String, Object> body,
                                                 @AuthenticationPrincipal AuthPrincipal caller) {
        boolean marked = Boolean.TRUE.equals(body.get("marked"));
        return ApiResponse.ok(service.setMark(id, caller.userId(), marked));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Map<String, Object>> delete(@PathVariable("id") Long id,
                                                   @AuthenticationPrincipal AuthPrincipal caller) {
        service.delete(id, caller.userId());
        return ApiResponse.ok(Map.of("deleted", true));
    }

    /** keep_marked=true (default) → 清除未標記; false → 清空全部。 */
    @DeleteMapping
    public ApiResponse<Map<String, Object>> clear(
            @RequestParam(name = "keep_marked", defaultValue = "true") boolean keepMarked,
            @AuthenticationPrincipal AuthPrincipal caller) {
        return ApiResponse.ok(service.clear(caller.userId(), keepMarked));
    }
}
