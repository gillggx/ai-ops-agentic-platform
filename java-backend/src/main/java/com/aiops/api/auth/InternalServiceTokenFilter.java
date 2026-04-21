package com.aiops.api.auth;

import com.aiops.api.config.AiopsProperties;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.Arrays;
import java.util.EnumSet;
import java.util.HashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;

/**
 * Authenticates Python-sidecar → Java calls using {@code X-Internal-Token}.
 *
 * <p>Only activates on {@code /internal/**} paths. Populates
 * {@link SecurityContextHolder} with:
 * <ul>
 *   <li>Authority {@link InternalAuthority#PYTHON_SIDECAR} for RBAC on the controller.</li>
 *   <li>An {@link AuthPrincipal} built from the forwarded {@code X-User-*} headers,
 *       so audit logs capture the real originating user, not the sidecar.</li>
 * </ul>
 */
@Slf4j
@Component
public class InternalServiceTokenFilter extends OncePerRequestFilter {

	private final AiopsProperties props;
	private final Set<String> allowedIps;

	public InternalServiceTokenFilter(AiopsProperties props) {
		this.props = props;
		this.allowedIps = parseAllowedIps(props.internal().allowedCallerIps());
	}

	@Override
	protected boolean shouldNotFilter(HttpServletRequest request) {
		return !request.getRequestURI().startsWith("/internal/");
	}

	@Override
	protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
			throws ServletException, IOException {
		String token = req.getHeader("X-Internal-Token");
		String expected = props.internal().token();
		if (token == null || !token.equals(expected)) {
			reject(res, "invalid or missing X-Internal-Token");
			return;
		}
		if (!allowedIps.isEmpty() && !allowedIps.contains(req.getRemoteAddr())) {
			log.warn("internal call from disallowed ip {}", req.getRemoteAddr());
			reject(res, "caller ip not allowed");
			return;
		}

		AuthPrincipal principal = buildForwardedPrincipal(req);
		var auth = new UsernamePasswordAuthenticationToken(
				principal, null,
				List.of(new SimpleGrantedAuthority(InternalAuthority.PYTHON_SIDECAR)));
		SecurityContextHolder.getContext().setAuthentication(auth);
		try {
			chain.doFilter(req, res);
		} finally {
			SecurityContextHolder.clearContext();
		}
	}

	private AuthPrincipal buildForwardedPrincipal(HttpServletRequest req) {
		Long userId = Optional.ofNullable(req.getHeader("X-User-Id"))
				.filter(s -> !s.isBlank())
				.map(s -> {
					try { return Long.valueOf(s.trim()); } catch (NumberFormatException e) { return null; }
				})
				.orElse(null);
		String username = Optional.ofNullable(req.getHeader("X-User-Name")).orElse("python-sidecar");
		Set<Role> roles = EnumSet.noneOf(Role.class);
		String roleHeader = req.getHeader("X-User-Roles");
		if (roleHeader != null && !roleHeader.isBlank()) {
			Arrays.stream(roleHeader.split(","))
					.map(String::trim)
					.map(Role::fromString)
					.flatMap(Optional::stream)
					.forEach(roles::add);
		}
		return new AuthPrincipal(userId, username, roles);
	}

	private void reject(HttpServletResponse res, String msg) throws IOException {
		res.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
		res.setContentType("application/json");
		res.getWriter().write("{\"ok\":false,\"error\":{\"code\":\"unauthorized\",\"message\":\"" + msg + "\"}}");
	}

	private Set<String> parseAllowedIps(String csv) {
		if (csv == null || csv.isBlank()) return Set.of();
		Set<String> out = new HashSet<>();
		for (String s : csv.split(",")) {
			String t = s.trim();
			if (!t.isEmpty()) out.add(t);
		}
		return Set.copyOf(out);
	}
}
