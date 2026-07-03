package com.aiops.api.api.supervisor;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * Supervisor curation review surface (Phase 5, V72). Human-in-the-loop:
 * list proposals → approve (commits the mutation) / reject (audit only).
 * ADMIN_OR_PE — same tier as the knowledge pages it curates.
 */
@RestController
@RequestMapping("/api/v1/supervisor")
@PreAuthorize(Authorities.ADMIN_OR_PE)
public class SupervisorController {

    private final SupervisorCurationService service;

    public SupervisorController(SupervisorCurationService service) {
        this.service = service;
    }

    @GetMapping("/proposals")
    public ApiResponse<List<Map<String, Object>>> list(
            @RequestParam(name = "status", required = false) String status) {
        return ApiResponse.ok(service.list(status));
    }

    @GetMapping("/proposals/counts")
    public ApiResponse<Map<String, Object>> counts() {
        return ApiResponse.ok(service.counts());
    }

    @PostMapping("/proposals/{id}/approve")
    public ApiResponse<Map<String, Object>> approve(@PathVariable("id") Long id,
                                                    @AuthenticationPrincipal AuthPrincipal caller) {
        return ApiResponse.ok(service.approve(id, caller.userId()));
    }

    @PostMapping("/proposals/{id}/reject")
    public ApiResponse<Map<String, Object>> reject(@PathVariable("id") Long id,
                                                   @AuthenticationPrincipal AuthPrincipal caller) {
        return ApiResponse.ok(service.reject(id, caller.userId()));
    }
}
