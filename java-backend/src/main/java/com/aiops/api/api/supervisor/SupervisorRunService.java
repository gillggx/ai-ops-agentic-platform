package com.aiops.api.api.supervisor;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.JsonUtils;
import com.aiops.api.sidecar.PythonSidecarClient;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Manual Supervisor run trigger — thin composition over the sidecar's
 * {@code POST /internal/supervisor/runs} + {@code GET /internal/supervisor/runs/status}.
 * The run itself (proposer LLM, deep dives) lives entirely in the sidecar;
 * Java only (a) optionally clears the pending proposal queue first and
 * (b) forwards / passes through the sidecar JSON.
 *
 * <p>409 mapping (documented contract): the sidecar answers 409
 * {@code {"running": true, ...}} when a run is already in flight. We surface
 * that as HTTP 409 {@code ApiResponse.fail} with code
 * {@code supervisor_run_in_progress} and the sidecar body (plus the
 * {@code cleared} count — the clear has already committed by then, the
 * caller must know it happened) under {@code error.details}.
 *
 * <p>Ordering: validate → clearPending → forward. Validation failures never
 * clear the queue; a sidecar conflict/outage after a clear is reported with
 * the count so nothing is silently lost.
 */
@Service
public class SupervisorRunService {

    static final String RUNS_PATH = "/internal/supervisor/runs";
    static final String RUNS_STATUS_PATH = "/internal/supervisor/runs/status";

    private final SupervisorCurationService curation;
    private final PythonSidecarClient sidecar;
    private final ObjectMapper mapper;

    public SupervisorRunService(SupervisorCurationService curation,
                                PythonSidecarClient sidecar,
                                ObjectMapper mapper) {
        this.curation = curation;
        this.sidecar = sidecar;
        this.mapper = mapper;
    }

    /** Body: {@code {kind, days?, max_deep_dives?, clear_pending?}} (snake_case).
     *  Success wire shape: {@code {"cleared": n, "run_id": "...", "started": true}}
     *  — {@code cleared} prepended by Java, the rest is the sidecar's JSON as-is. */
    public Map<String, Object> trigger(Map<String, Object> body, AuthPrincipal caller) {
        if (body == null || !(body.get("kind") instanceof String kind) || kind.isBlank()) {
            throw ApiException.badRequest("kind required (string)");
        }
        Integer days = asInt(body, "days");
        Integer maxDeepDives = asInt(body, "max_deep_dives");
        Object clearFlag = body.get("clear_pending");
        if (clearFlag != null && !(clearFlag instanceof Boolean)) {
            // loud, not silent — a string "true" must not quietly skip the clear
            throw ApiException.badRequest("clear_pending must be a boolean");
        }
        boolean clearPending = Boolean.TRUE.equals(clearFlag);

        int cleared = clearPending ? curation.clearPending(caller.userId()) : 0;

        Map<String, Object> forward = new LinkedHashMap<>();
        forward.put("kind", kind);
        if (days != null) forward.put("days", days);
        if (maxDeepDives != null) forward.put("max_deep_dives", maxDeepDives);

        Map<String, Object> sidecarBody = postRuns(forward, caller, cleared);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("cleared", cleared);
        if (sidecarBody != null) out.putAll(sidecarBody);
        return out;
    }

    /** Passthrough of the sidecar's run-status JSON, verbatim. */
    public Map<String, Object> status(AuthPrincipal caller) {
        try {
            Map<String, Object> res = getJsonMap(RUNS_STATUS_PATH, caller);
            return res == null ? Map.of() : res;
        } catch (WebClientRequestException e) {
            throw ApiException.serviceUnavailable(
                    "sidecar unreachable for supervisor run status: " + e.getMessage());
        }
    }

    private Map<String, Object> postRuns(Map<String, Object> forward, AuthPrincipal caller,
                                         int cleared) {
        try {
            return postJsonMap(RUNS_PATH, forward, caller);
        } catch (WebClientResponseException.Conflict e) {
            // Sidecar 409 {"running": true, ...} → 409 here as well; keep the
            // sidecar body AND the already-committed cleared count visible.
            Map<String, Object> details = new LinkedHashMap<>();
            details.put("cleared", cleared);
            details.putAll(JsonUtils.parseObject(mapper, e.getResponseBodyAsString()));
            throw new ApiException(HttpStatus.CONFLICT, "supervisor_run_in_progress",
                    "a supervisor run is already in progress", details);
        } catch (WebClientRequestException e) {
            throw ApiException.serviceUnavailable(
                    "sidecar unreachable for supervisor run trigger (cleared=" + cleared + "): "
                            + e.getMessage());
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> postJsonMap(String path, Object body, AuthPrincipal caller) {
        return (Map<String, Object>) sidecar.postJson(path, body, Map.class, caller).block();
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> getJsonMap(String path, AuthPrincipal caller) {
        return (Map<String, Object>) sidecar.getJson(path, Map.class, caller).block();
    }

    /** Optional int field — absent/null → null; non-numeric → loud badRequest
     *  (silent coercion would make a typo look like "used the default"). */
    private static Integer asInt(Map<String, Object> body, String key) {
        Object v = body.get(key);
        if (v == null) return null;
        if (v instanceof Number n) return n.intValue();
        if (v instanceof String s && !s.isBlank()) {
            try {
                return Integer.parseInt(s.trim());
            } catch (NumberFormatException e) {
                throw ApiException.badRequest(key + " must be an integer, got: " + s);
            }
        }
        throw ApiException.badRequest(key + " must be an integer");
    }
}
