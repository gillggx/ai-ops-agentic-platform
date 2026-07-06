package com.aiops.api.api.supervisor;

import com.aiops.api.api.llm.LlmUsageService;
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
 *
 * <p>W2 (V75): reject accepts an optional {@code {"reason": "..."}} body;
 * /metrics/llm-daily exposes the S3 provider-quality rollup.
 *
 * <p>Manual run trigger: /runs + /runs/status forward to the sidecar's
 * internal supervisor-run endpoints. IT_ADMIN only (method-level
 * {@code @PreAuthorize} overrides the class-level ADMIN_OR_PE) — a manual
 * run burns LLM budget and can bulk-reject the whole proposal queue.
 */
@RestController
@RequestMapping("/api/v1/supervisor")
@PreAuthorize(Authorities.ADMIN_OR_PE)
public class SupervisorController {

    private final SupervisorCurationService service;
    private final SupervisorRunService runs;
    private final LlmUsageService llmUsage;

    public SupervisorController(SupervisorCurationService service,
                                SupervisorRunService runs,
                                LlmUsageService llmUsage) {
        this.service = service;
        this.runs = runs;
        this.llmUsage = llmUsage;
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
                                                   @RequestBody(required = false) Map<String, Object> body,
                                                   @AuthenticationPrincipal AuthPrincipal caller) {
        String reason = body == null || body.get("reason") == null
                ? null : String.valueOf(body.get("reason"));
        return ApiResponse.ok(service.reject(id, caller.userId(), reason));
    }

    /** Manual Supervisor run. Body {@code {kind, days?, max_deep_dives?,
     *  clear_pending?}}; with clear_pending=true the proposed queue is
     *  bulk-rejected first. 200 → {@code {"cleared": n, "run_id": "...",
     *  "started": true}}; run already in flight → HTTP 409
     *  (code {@code supervisor_run_in_progress}, sidecar body + cleared
     *  count in error.details). */
    @PostMapping("/runs")
    @PreAuthorize(Authorities.ADMIN)
    public ApiResponse<Map<String, Object>> triggerRun(@RequestBody Map<String, Object> body,
                                                       @AuthenticationPrincipal AuthPrincipal caller) {
        return ApiResponse.ok(runs.trigger(body, caller));
    }

    /** Passthrough of the sidecar's supervisor run status. */
    @GetMapping("/runs/status")
    @PreAuthorize(Authorities.ADMIN)
    public ApiResponse<Map<String, Object>> runStatus(@AuthenticationPrincipal AuthPrincipal caller) {
        return ApiResponse.ok(runs.status(caller));
    }

    /** S3 (V75): LLM provider quality — daily rollup of calls / empty /
     *  error / tokens per model, newest day first. */
    @GetMapping("/metrics/llm-daily")
    public ApiResponse<List<Map<String, Object>>> llmDaily(
            @RequestParam(name = "days", defaultValue = "7") int days) {
        return ApiResponse.ok(llmUsage.daily(days));
    }
}
