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
	                          String mode, Map<String, Object> pipelineSnapshot) {}

	public record BuildRequest(@NotBlank String instruction,
	                           Long pipelineId,
	                           Map<String, Object> pipelineSnapshot,
	                           Map<String, Object> triggerPayload) {}
}
