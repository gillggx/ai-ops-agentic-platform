package com.aiops.api.audit;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.domain.audit.AuditLogEntity;
import com.aiops.api.domain.audit.AuditLogRepository;
import jakarta.servlet.http.HttpServletRequest;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Async;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;

import java.util.stream.Collectors;

/**
 * Writes audit entries asynchronously so controller latency is unaffected.
 * Only mutating requests (POST/PUT/PATCH/DELETE) produce entries.
 */
@Slf4j
@Service
public class AuditLogService {

	private static final int MAX_BODY_CHARS = 2000;

	private final AuditLogRepository repository;

	public AuditLogService(AuditLogRepository repository) {
		this.repository = repository;
	}

	@Async
	public void record(HttpServletRequest request, int statusCode, long durationMs,
	                   String requestBody, String errorMessage) {
		String method = request.getMethod();
		if (!isMutation(method)) return;

		AuditLogEntity entry = new AuditLogEntity();
		entry.setHttpMethod(method);
		entry.setEndpoint(request.getRequestURI());
		entry.setStatusCode(statusCode);
		entry.setDurationMs(durationMs);
		entry.setRemoteIp(extractRemoteIp(request));
		entry.setUserAgent(truncate(request.getHeader("User-Agent"), 500));
		entry.setRequestBody(truncate(requestBody, MAX_BODY_CHARS));
		entry.setErrorMessage(truncate(errorMessage, MAX_BODY_CHARS));

		var auth = SecurityContextHolder.getContext().getAuthentication();
		if (auth != null && auth.getPrincipal() instanceof AuthPrincipal ap) {
			entry.setUserId(ap.userId());
			entry.setUsername(ap.username());
			entry.setRoles(ap.roles().stream().map(Enum::name).collect(Collectors.joining("|")));
		}

		try {
			repository.save(entry);
		} catch (Exception ex) {
			log.warn("Failed to persist audit log entry: {}", ex.getMessage());
		}
	}

	private boolean isMutation(String method) {
		return "POST".equals(method) || "PUT".equals(method)
				|| "PATCH".equals(method) || "DELETE".equals(method);
	}

	private String extractRemoteIp(HttpServletRequest r) {
		String fwd = r.getHeader("X-Forwarded-For");
		if (fwd != null && !fwd.isBlank()) return fwd.split(",")[0].trim();
		return r.getRemoteAddr();
	}

	private String truncate(String s, int max) {
		if (s == null) return null;
		return s.length() <= max ? s : s.substring(0, max);
	}
}
