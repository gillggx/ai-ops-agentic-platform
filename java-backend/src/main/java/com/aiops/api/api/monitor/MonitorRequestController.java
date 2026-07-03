package com.aiops.api.api.monitor;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * Monitor improvement-request review surface (Phase 6, V73). Human-in-the-loop:
 * scan (on demand) → open requests → approve (get the prepared instruction to
 * launch at the Planner) / dismiss.
 */
@RestController
@RequestMapping("/api/v1/monitor")
@PreAuthorize(Authorities.ADMIN_OR_PE)
public class MonitorRequestController {

    private final MonitorService service;

    public MonitorRequestController(MonitorService service) {
        this.service = service;
    }

    @PostMapping("/scan")
    public ApiResponse<Map<String, Object>> scan() {
        return ApiResponse.ok(service.scan());
    }

    @GetMapping("/requests")
    public ApiResponse<List<Map<String, Object>>> list(
            @RequestParam(name = "status", required = false) String status) {
        return ApiResponse.ok(service.list(status));
    }

    @PostMapping("/requests/{id}/approve")
    public ApiResponse<Map<String, Object>> approve(@PathVariable("id") Long id,
                                                    @AuthenticationPrincipal AuthPrincipal caller) {
        return ApiResponse.ok(service.review(id, caller.userId(), true));
    }

    @PostMapping("/requests/{id}/dismiss")
    public ApiResponse<Map<String, Object>> dismiss(@PathVariable("id") Long id,
                                                    @AuthenticationPrincipal AuthPrincipal caller) {
        return ApiResponse.ok(service.review(id, caller.userId(), false));
    }
}
