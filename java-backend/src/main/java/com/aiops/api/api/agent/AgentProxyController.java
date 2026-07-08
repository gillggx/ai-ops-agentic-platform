package com.aiops.api.api.agent;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.common.RequestBodyAccess;
import com.aiops.api.common.SseEmitterBridge;
import com.aiops.api.sidecar.PythonSidecarClient;
import org.springframework.http.MediaType;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static com.aiops.api.common.RequestBodyAccess.asBool;
import static com.aiops.api.common.RequestBodyAccess.asLong;
import static com.aiops.api.common.RequestBodyAccess.pickAlias;
import static com.aiops.api.common.RequestBodyAccess.pickMapAlias;
import static com.aiops.api.common.RequestBodyAccess.requireAlias;

/**
 * SSE + JSON proxy for everything that still runs in Python:
 * LangGraph chat, Pipeline Builder Glass Box, Pipeline Executor, Sandbox.
 *
 * <p>Design: we live in Spring MVC (servlet stack). Returning {@code Mono}/{@code Flux}
 * triggers async dispatch which confuses the stateless JWT filter. So JSON paths
 * {@code .block()} the {@code Mono} on the calling thread, and SSE paths bridge
 * the reactive {@code Flux} into an {@link SseEmitter} via {@link SseEmitterBridge}
 * — which is the MVC-native SSE primitive and plays nicely with the security
 * filter chain.
 *
 * <p>Auth: chat is open to ANY_ROLE (ON_DUTY can ask the agent questions —
 * the sidecar's tool filter denies them build/write tools at the LLM layer);
 * build / pipeline.execute / sandbox.run stay PE+ since those are write paths.
 *
 * <p>2026-05-23 (Phase 12): Each SSE-relay endpoint historically accepted
 * both legacy camelCase (pre-cutover Frontend clients) and canonical
 * snake_case keys. The alias-pick boilerplate is now in
 * {@link RequestBodyAccess} — endpoints stay readable.
 */
@RestController
@RequestMapping("/api/v1/agent")
public class AgentProxyController {

	private final PythonSidecarClient sidecar;
	private final SseEmitterBridge sseBridge;

	public AgentProxyController(PythonSidecarClient sidecar, SseEmitterBridge sseBridge) {
		this.sidecar = sidecar;
		this.sseBridge = sseBridge;
	}

	// ── SSE: chat + chat-stream compat ──────────────────────────────────────

	@PostMapping(path = "/chat", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	@PreAuthorize(Authorities.ANY_ROLE)
	public SseEmitter chat(@Validated @RequestBody AgentProxyDtos.ChatRequest req,
	                       @AuthenticationPrincipal AuthPrincipal caller) {
		return sseBridge.bridge(sidecar.postSse("/internal/agent/chat", req, caller), "chat");
	}

	/** Legacy alias: Frontend historically posted to {@code /chat/stream}
	 *  with a {@code prompt} field (old Python FastAPI shape). Accept both
	 *  paths and both field names so the Next.js proxy keeps working
	 *  post-cutover without a redeploy. */
	@PostMapping(path = "/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	@PreAuthorize(Authorities.ANY_ROLE)
	public SseEmitter chatStreamCompat(@RequestBody Map<String, Object> body,
	                                   @AuthenticationPrincipal AuthPrincipal caller) {
		String message = requireAlias(body, "message", "message", "prompt");
		String sessionId = pickAlias(body, "sessionId", "session_id");
		// Part B: forward client_context (selected_equipment_id etc.) if present.
		Map<String, Object> clientContext = pickMapAlias(body, "clientContext", "client_context");
		// Phase E2/E3: when AIAgentPanel runs inside BuilderLayout it ships
		// mode="builder" + pipeline_snapshot. Without this passthrough the
		// sidecar's mode-aware prompt never activates.
		String mode = pickAlias(body, "mode");
		Map<String, Object> pipelineSnapshot = pickMapAlias(body, "pipelineSnapshot", "pipeline_snapshot");
		// 2026-07-08 modify-mode: forward per-node output columns so the
		// sidecar Coordinator can build a column-aware situation report.
		Map<String, Object> pipelineColumns = pickMapAlias(body, "pipelineColumns", "pipeline_columns");
		AgentProxyDtos.ChatRequest req = new AgentProxyDtos.ChatRequest(
				message, sessionId, clientContext, mode, pipelineSnapshot, pipelineColumns);
		return sseBridge.bridge(sidecar.postSse("/internal/agent/chat", req, caller), "chat");
	}

	// ── SSE: build + resume ─────────────────────────────────────────────────

	/** Accepts both the new contract ({instruction, pipelineId, pipelineSnapshot})
	 *  and the legacy Python-era contract ({prompt, base_pipeline_id, base_pipeline})
	 *  so Frontend clients that were not redeployed with the Java cutover keep working. */
	@PostMapping(path = "/build", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public SseEmitter build(@RequestBody Map<String, Object> body,
	                        @AuthenticationPrincipal AuthPrincipal caller) {
		String instruction = requireAlias(body, "instruction", "instruction", "prompt");
		Long pipelineId = asLong(body.get("pipelineId"));
		if (pipelineId == null) pipelineId = asLong(body.get("base_pipeline_id"));
		Map<String, Object> snapshot = pickMapAlias(body, "pipelineSnapshot", "base_pipeline");
		// 2026-05-13: pass triggerPayload through so sidecar's dry-run uses
		// the same inputs that production /run will. Without this, dry-run
		// uses canonical fallbacks (tool_id=EQP-01 etc.) which often differ
		// from the actual trigger and let runtime-only failures slip past
		// inspect/reflect.
		Map<String, Object> triggerPayload = pickMapAlias(body, "triggerPayload", "trigger_payload");
		AgentProxyDtos.BuildRequest req = new AgentProxyDtos.BuildRequest(
				instruction, pipelineId, snapshot, triggerPayload);
		return sseBridge.bridge(sidecar.postSse("/internal/agent/build", req, caller), "build");
	}

	/** Phase 10 (graph_build v2) — resume a paused build at confirm_gate.
	 *  Body: { sessionId | session_id, confirmed: bool } */
	@PostMapping(path = "/build/confirm", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public SseEmitter buildConfirm(@RequestBody Map<String, Object> body,
	                               @AuthenticationPrincipal AuthPrincipal caller) {
		String sessionId = requireAlias(body, "session_id", "sessionId", "session_id");
		Map<String, Object> req = new HashMap<>();
		req.put("session_id", sessionId);
		req.put("confirmed", asBool(body.get("confirmed")));
		return sseBridge.bridge(sidecar.postSse("/internal/agent/build/confirm", req, caller), "build_confirm");
	}

	/** v15 G1 (2026-05-13) — resume paused graph at clarify_intent_node.
	 *  Body: { sessionId | session_id, answers: {qid: value} } */
	@PostMapping(path = "/build/clarify-respond", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public SseEmitter buildClarifyRespond(@RequestBody Map<String, Object> body,
	                                      @AuthenticationPrincipal AuthPrincipal caller) {
		String sessionId = requireAlias(body, "session_id", "sessionId", "session_id");
		Map<String, Object> answers = pickMapAlias(body, "answers");
		if (answers == null) answers = new HashMap<>();
		Map<String, Object> req = new HashMap<>();
		req.put("session_id", sessionId);
		req.put("answers", answers);
		return sseBridge.bridge(sidecar.postSse("/internal/agent/build/clarify-respond", req, caller), "build_clarify");
	}

	/** v30 (2026-05-16) — resume paused graph at goal_plan_confirm_gate.
	 *  Body: { sessionId | session_id, confirmed: bool, phases?: [...] } */
	@PostMapping(path = "/build/plan-confirm", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public SseEmitter buildPlanConfirm(@RequestBody Map<String, Object> body,
	                                   @AuthenticationPrincipal AuthPrincipal caller) {
		String sessionId = requireAlias(body, "session_id", "sessionId", "session_id");
		Map<String, Object> req = new HashMap<>();
		req.put("session_id", sessionId);
		req.put("confirmed", asBool(body.get("confirmed")));
		Object phases = body.get("phases");
		if (phases instanceof List<?>) req.put("phases", phases);
		return sseBridge.bridge(sidecar.postSse("/internal/agent/build/plan-confirm", req, caller), "build_plan_confirm");
	}

	/** v30 — resume paused graph at halt_handover.
	 *  Body: { sessionId, choice: 'edit_goal'|'take_over'|'backlog'|'abort', newGoal?: string } */
	@PostMapping(path = "/build/handover", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public SseEmitter buildHandover(@RequestBody Map<String, Object> body,
	                                @AuthenticationPrincipal AuthPrincipal caller) {
		String sessionId = requireAlias(body, "session_id", "sessionId", "session_id");
		String choice = requireAlias(body, "choice", "choice");
		Map<String, Object> req = new HashMap<>();
		req.put("session_id", sessionId);
		req.put("choice", choice);
		String newGoal = pickAlias(body, "newGoal", "new_goal");
		if (newGoal != null) req.put("new_goal", newGoal);
		return sseBridge.bridge(sidecar.postSse("/internal/agent/build/handover", req, caller), "build_handover");
	}

	/** v15 G2 — modify request after plan review.
	 *  Body: { sessionId | session_id, stepIdx?: int, request: string } */
	@PostMapping(path = "/build/modify-request", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	public SseEmitter buildModifyRequest(@RequestBody Map<String, Object> body,
	                                     @AuthenticationPrincipal AuthPrincipal caller) {
		String sessionId = requireAlias(body, "session_id", "sessionId", "session_id");
		String request = requireAlias(body, "request", "request");
		Long stepIdx = asLong(body.get("stepIdx"));
		if (stepIdx == null) stepIdx = asLong(body.get("step_idx"));
		Map<String, Object> req = new HashMap<>();
		req.put("session_id", sessionId);
		req.put("step_idx", stepIdx);
		req.put("request", request);
		return sseBridge.bridge(sidecar.postSse("/internal/agent/build/modify-request", req, caller), "build_modify");
	}

	// ── JSON paths: pipeline + sandbox (block() is intentional) ─────────────

	@PostMapping("/pipeline/execute")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	@SuppressWarnings({"unchecked", "rawtypes"})
	public ApiResponse<Map> pipelineExecute(@RequestBody Map<String, Object> body,
	                                        @AuthenticationPrincipal AuthPrincipal caller) {
		Map result = sidecar.postJson("/internal/pipeline/execute", body, Map.class, caller).block();
		return ApiResponse.ok(result);
	}

	@PostMapping("/pipeline/validate")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	@SuppressWarnings({"unchecked", "rawtypes"})
	public ApiResponse<Map> pipelineValidate(@RequestBody Map<String, Object> body,
	                                         @AuthenticationPrincipal AuthPrincipal caller) {
		Map result = sidecar.postJson("/internal/pipeline/validate", body, Map.class, caller).block();
		return ApiResponse.ok(result);
	}

	@PostMapping("/sandbox/run")
	@PreAuthorize(Authorities.ADMIN_OR_PE)
	@SuppressWarnings({"unchecked", "rawtypes"})
	public ApiResponse<Map> sandbox(@RequestBody Map<String, Object> body,
	                                @AuthenticationPrincipal AuthPrincipal caller) {
		Map result = sidecar.postJson("/internal/sandbox/run", body, Map.class, caller).block();
		return ApiResponse.ok(result);
	}

	@GetMapping("/sidecar/health")
	@PreAuthorize(Authorities.ANY_ROLE)
	@SuppressWarnings({"unchecked", "rawtypes"})
	public ApiResponse<Map> sidecarHealth(@AuthenticationPrincipal AuthPrincipal caller) {
		Map result = sidecar.getJson("/internal/health", Map.class, caller).block();
		return ApiResponse.ok(result);
	}
}
