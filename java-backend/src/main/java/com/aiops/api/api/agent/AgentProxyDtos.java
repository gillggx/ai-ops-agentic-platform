package com.aiops.api.api.agent;

import jakarta.validation.constraints.NotBlank;

import java.util.Map;

/**
 * HTTP-layer DTOs for {@link AgentProxyController}.
 *
 * <p>Extracted from {@code AgentProxyController} 2026-05-23 as part of the
 * Phase 12 Java OOP refactor for consistency with the
 * SkillDocumentController / PipelineController pattern (DTOs in their own
 * file rather than nested inside the controller class).
 */
public final class AgentProxyDtos {

	private AgentProxyDtos() {}

	public record ChatRequest(@NotBlank String message, String sessionId,
	                          Map<String, Object> clientContext,
	                          String mode, Map<String, Object> pipelineSnapshot,
	                          // 2026-07-08 modify-mode: per-node output columns of
	                          // the on-screen pipeline (from the last card's
	                          // node_results) — lets the sidecar Coordinator build
	                          // a column-aware situation report without a harvest
	                          // re-execute. {node_id: [col, ...]}.
	                          Map<String, Object> pipelineColumns,
	                          // P3 (2026-07-13) 貼圖：data URL 圖片，透傳 sidecar。
	                          java.util.List<String> images) {}

	public record BuildRequest(@NotBlank String instruction,
	                           Long pipelineId,
	                           Map<String, Object> pipelineSnapshot,
	                           Map<String, Object> triggerPayload) {}
}
