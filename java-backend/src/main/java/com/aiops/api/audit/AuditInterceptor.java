package com.aiops.api.audit;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

/**
 * Captures request timing and hands it off to {@link AuditLogService} asynchronously.
 * Skips the audit endpoint itself to avoid recursion.
 */
@Component
public class AuditInterceptor implements HandlerInterceptor {

	private static final String START_ATTR = "aiops.audit.start";

	private final AuditLogService auditService;

	public AuditInterceptor(AuditLogService auditService) {
		this.auditService = auditService;
	}

	@Override
	public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
		request.setAttribute(START_ATTR, System.nanoTime());
		return true;
	}

	@Override
	public void afterCompletion(HttpServletRequest request, HttpServletResponse response,
	                            Object handler, Exception ex) {
		if (shouldSkip(request)) return;
		long start = (long) request.getAttribute(START_ATTR);
		long durationMs = (System.nanoTime() - start) / 1_000_000L;
		auditService.record(request, response.getStatus(), durationMs, null,
				ex == null ? null : ex.getMessage());
	}

	private boolean shouldSkip(HttpServletRequest req) {
		String uri = req.getRequestURI();
		return uri.startsWith("/actuator")
				|| uri.startsWith("/api/v1/health")
				|| uri.startsWith("/api/v1/admin/audit");
	}
}
