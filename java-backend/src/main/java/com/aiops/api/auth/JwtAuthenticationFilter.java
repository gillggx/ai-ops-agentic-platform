package com.aiops.api.auth;

import com.auth0.jwt.exceptions.JWTVerificationException;
import com.aiops.api.config.AiopsProperties;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.authentication.WebAuthenticationDetailsSource;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;

/**
 * Stateless JWT filter — only active when {@code aiops.auth.mode=local}.
 * Reads {@code Authorization: Bearer <token>}, validates, and populates the
 * Spring {@link SecurityContextHolder} with an {@link AuthPrincipal}.
 */
@Slf4j
@Component
public class JwtAuthenticationFilter extends OncePerRequestFilter {

	private final JwtService jwtService;
	private final AiopsProperties props;

	public JwtAuthenticationFilter(JwtService jwtService, AiopsProperties props) {
		this.jwtService = jwtService;
		this.props = props;
	}

	@Override
	protected boolean shouldNotFilter(HttpServletRequest request) {
		return props.auth().mode() != AiopsProperties.Auth.Mode.local;
	}

	@Override
	protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
			throws ServletException, IOException {
		String auth = req.getHeader("Authorization");
		if (auth != null && auth.startsWith("Bearer ")) {
			String token = auth.substring("Bearer ".length());
			try {
				AuthPrincipal principal = jwtService.verify(token);
				List<SimpleGrantedAuthority> authorities = principal.roles().stream()
						.map(r -> new SimpleGrantedAuthority(r.authority()))
						.toList();
				var authentication = new UsernamePasswordAuthenticationToken(
						principal, null, authorities);
				authentication.setDetails(new WebAuthenticationDetailsSource().buildDetails(req));
				SecurityContextHolder.getContext().setAuthentication(authentication);
			} catch (JWTVerificationException ex) {
				log.debug("JWT verification failed: {}", ex.getMessage());
				SecurityContextHolder.clearContext();
			}
		}
		chain.doFilter(req, res);
	}
}
