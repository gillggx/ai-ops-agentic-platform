package com.aiops.api.auth;

import com.aiops.api.config.AiopsProperties;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.EnumSet;
import java.util.List;

/**
 * Accepts a long-lived shared-secret token used by the old Python FastAPI as
 * an alternative to JWT. When the Frontend is mid-cutover, its
 * {@code INTERNAL_API_TOKEN} (48-char hex) doesn't parse as a JWT, so the JWT
 * filter rejects it. This filter runs FIRST: if the Bearer value equals
 * {@code aiops.auth.shared-secret-token}, we pretend it's an IT_ADMIN
 * principal and populate {@link SecurityContextHolder}.
 *
 * <p>Safe because the shared secret lives in env only and is the same one
 * Python has been trusting. When parity is reached and Frontend switches to
 * Java-issued JWTs, drop this filter (or blank the env var).
 */
@Component
public class SharedSecretAuthFilter extends OncePerRequestFilter {

	private final AiopsProperties props;

	public SharedSecretAuthFilter(AiopsProperties props) {
		this.props = props;
	}

	@Override
	protected boolean shouldNotFilter(HttpServletRequest request) {
		// Don't interfere with /internal/* (has its own service-token filter)
		return request.getRequestURI().startsWith("/internal/");
	}

	/**
	 * OncePerRequestFilter skips async dispatches by default, which drops the
	 * SecurityContext when Spring re-runs the filter chain after SseEmitter
	 * completes. AuthorizationFilter then sees an empty context and throws
	 * AuthorizationDeniedException, which can't be handled because the SSE
	 * response is already committed → Tomcat drops the connection → browser
	 * fetch reader sees 'terminated'. Re-apply the shared-secret auth on
	 * async dispatch so the context survives.
	 */
	@Override
	protected boolean shouldNotFilterAsyncDispatch() {
		return false;
	}

	@Override
	protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
			throws ServletException, IOException {
		String secret = props.auth().sharedSecretToken();
		if (secret != null && !secret.isBlank()) {
			String authHeader = req.getHeader("Authorization");
			if (authHeader != null && authHeader.startsWith("Bearer ")
					&& secret.equals(authHeader.substring("Bearer ".length()))) {
				// userId=1L points at the admin seed row in `users`. Previously
				// 0L, which violated pb_pipelines.created_by FK whenever the
				// shared-secret bearer hit a controller that calls
				// `caller.userId()` (create / fork pipeline, etc.). The
				// shared-secret is already trusted as IT_ADMIN; aligning to
				// the admin user_id keeps server-to-server / smoke flows
				// working without touching prod user JWT paths.
				AuthPrincipal principal = new AuthPrincipal(
						1L, "shared-secret-admin", EnumSet.of(Role.IT_ADMIN));
				var auth = new UsernamePasswordAuthenticationToken(
						principal, null,
						List.of(new SimpleGrantedAuthority(Role.IT_ADMIN.authority())));
				SecurityContextHolder.getContext().setAuthentication(auth);
			}
		}
		chain.doFilter(req, res);
	}
}
