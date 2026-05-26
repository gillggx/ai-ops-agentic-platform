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
import org.springframework.security.web.util.matcher.IpAddressMatcher;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.EnumSet;
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
	/** Compiled allow-list. Each entry handles both single IPs and CIDR
	 *  ranges via Spring's {@link IpAddressMatcher} (a plain IP becomes a
	 *  /32 or /128 match internally). Empty list = allow-all (token still
	 *  gates the call). */
	private final List<IpAddressMatcher> allowedIpMatchers;

	public InternalServiceTokenFilter(AiopsProperties props) {
		this.props = props;
		this.allowedIpMatchers = parseAllowedIpMatchers(props.internal().allowedCallerIps());
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
		String remoteIp = req.getRemoteAddr();
		if (!allowedIpMatchers.isEmpty() && !ipAllowed(remoteIp)) {
			log.warn("internal call from disallowed ip {}", remoteIp);
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

	private boolean ipAllowed(String remoteIp) {
		if (remoteIp == null) return false;
		for (IpAddressMatcher m : allowedIpMatchers) {
			try {
				if (m.matches(remoteIp)) return true;
			} catch (IllegalArgumentException ignored) {
				// remoteIp not parseable — treat as no-match
			}
		}
		return false;
	}

	private static List<IpAddressMatcher> parseAllowedIpMatchers(String csv) {
		if (csv == null || csv.isBlank()) return List.of();
		List<IpAddressMatcher> out = new ArrayList<>();
		for (String s : csv.split(",")) {
			String t = s.trim();
			if (t.isEmpty()) continue;
			try {
				// IpAddressMatcher accepts both "10.0.0.1" (single IP, treated
				// as /32 or /128) and "172.16.0.0/12" CIDR. Malformed entries
				// are skipped with a warn so a typo doesn't lock everyone out.
				out.add(new IpAddressMatcher(t));
			} catch (IllegalArgumentException ex) {
				log.warn("ignoring malformed allowed-ip entry '{}': {}", t, ex.getMessage());
			}
		}
		return List.copyOf(out);
	}
}
