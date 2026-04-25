package com.aiops.api.config;

import com.aiops.api.auth.JwtAuthenticationFilter;
import com.aiops.api.auth.SharedSecretAuthFilter;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.annotation.Order;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

/**
 * Phase 2 security: JWT (local) or OIDC resource server (Azure AD), behind
 * {@code aiops.auth.mode}. Actuator health + auth endpoints are always public.
 */
@Configuration
@EnableMethodSecurity(prePostEnabled = true)
public class SecurityConfig {

	@Bean
	@Order(2)
	public SecurityFilterChain filterChain(HttpSecurity http,
	                                       UrlBasedCorsConfigurationSource cors,
	                                       AiopsProperties props,
	                                       JwtAuthenticationFilter jwtFilter,
	                                       SharedSecretAuthFilter sharedSecretFilter) throws Exception {
		AuthenticationEntryPoint unauthorizedEntry = (req, res, ex) -> {
			res.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
			res.setContentType("application/json");
			res.getWriter().write("{\"ok\":false,\"error\":{\"code\":\"unauthorized\",\"message\":\"authentication required\"}}");
		};
		org.springframework.security.web.access.AccessDeniedHandler forbiddenHandler = (req, res, ex) -> {
			res.setStatus(HttpServletResponse.SC_FORBIDDEN);
			res.setContentType("application/json");
			res.getWriter().write("{\"ok\":false,\"error\":{\"code\":\"forbidden\",\"message\":\"insufficient role\"}}");
		};

		http
				.cors(c -> c.configurationSource(cors))
				.csrf(AbstractHttpConfigurer::disable)
				.httpBasic(AbstractHttpConfigurer::disable)
				.formLogin(AbstractHttpConfigurer::disable)
				.sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
				.exceptionHandling(e -> e
						.authenticationEntryPoint(unauthorizedEntry)
						.accessDeniedHandler(forbiddenHandler))
				.authorizeHttpRequests(a -> a
						.requestMatchers(
								"/actuator/health/**",
								"/actuator/info",
								"/api/v1/auth/login",
								"/api/v1/auth/oidc-upsert",   // shared-secret auth inside controller
								"/api/v1/health"
						).permitAll()
						.anyRequest().authenticated()
				);

		if (props.auth().mode() == AiopsProperties.Auth.Mode.oidc) {
			String issuer = props.oidc().issuer();
			if (issuer != null && !issuer.isBlank()) {
				// Azure AD multi-tenant and common-endpoint issuers both expose
				// their JWKS under /discovery/v2.0/keys; for other IdPs (e.g.
				// Keycloak) point OIDC_JWK_URI at the right path.
				String jwkUri = props.oidc().jwkSetUri() != null && !props.oidc().jwkSetUri().isBlank()
						? props.oidc().jwkSetUri()
						: issuer.replaceFirst("/+$", "") + "/discovery/v2.0/keys";
				http.oauth2ResourceServer(o -> o.jwt(j -> j
						.jwkSetUri(jwkUri)
						.jwtAuthenticationConverter(oidcAuthenticationConverter(props))
				));
			}
		} else {
			http.addFilterBefore(jwtFilter, UsernamePasswordAuthenticationFilter.class);
		}

		// Shared-secret compat filter runs BEFORE JWT so legacy shared-secret tokens
		// (Frontend's existing INTERNAL_API_TOKEN) are recognised without rewriting the client.
		http.addFilterBefore(sharedSecretFilter, UsernamePasswordAuthenticationFilter.class);

		return http.build();
	}

	@Bean
	public PasswordEncoder passwordEncoder() {
		return new BCryptPasswordEncoder(12);
	}

	/**
	 * IT_ADMIN > PE > ON_DUTY — a user with IT_ADMIN role implicitly satisfies
	 * any {@code @PreAuthorize("hasRole('PE')")} check, and so on.
	 * Matches Sidebar menu visibility: IT_ADMIN sees everything (1-9),
	 * PE sees 1-3, ON_DUTY sees 1-2.
	 */
	@Bean
	public org.springframework.security.access.hierarchicalroles.RoleHierarchy roleHierarchy() {
		var h = new org.springframework.security.access.hierarchicalroles.RoleHierarchyImpl();
		h.setHierarchy("ROLE_IT_ADMIN > ROLE_PE\nROLE_PE > ROLE_ON_DUTY");
		return h;
	}

	/**
	 * Wire the hierarchy into method security so @PreAuthorize / hasRole / hasAnyRole
	 * respect it. Without this, hierarchy only applies to URL-level rules.
	 */
	@Bean
	static org.springframework.security.access.expression.method.DefaultMethodSecurityExpressionHandler
			methodSecurityExpressionHandler(
					org.springframework.security.access.hierarchicalroles.RoleHierarchy roleHierarchy) {
		var handler = new org.springframework.security.access.expression.method.DefaultMethodSecurityExpressionHandler();
		handler.setRoleHierarchy(roleHierarchy);
		return handler;
	}

	/**
	 * Maps Azure AD / OIDC token claims to Spring authorities.
	 *
	 * <p>Azure AD puts app roles in the {@code roles} claim by default; some
	 * tenants use {@code groups}. We accept either (via {@code OIDC_ROLE_CLAIM}).
	 * Each value is prefixed with {@code ROLE_} so {@code @PreAuthorize("hasRole('IT_ADMIN')")}
	 * keeps working identically to local-JWT auth.
	 */
	private org.springframework.core.convert.converter.Converter<
			org.springframework.security.oauth2.jwt.Jwt,
			org.springframework.security.authentication.AbstractAuthenticationToken>
			oidcAuthenticationConverter(AiopsProperties props) {
		String roleClaim = props.oidc().roleClaim();
		if (roleClaim == null || roleClaim.isBlank()) roleClaim = "roles";
		String claimName = roleClaim;
		var delegate = new org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationConverter();
		delegate.setJwtGrantedAuthoritiesConverter(jwt -> {
			Object raw = jwt.getClaim(claimName);
			java.util.List<String> values = new java.util.ArrayList<>();
			if (raw instanceof java.util.Collection<?> c) {
				for (Object o : c) if (o != null) values.add(String.valueOf(o));
			} else if (raw instanceof String s && !s.isBlank()) {
				for (String v : s.split(",")) if (!v.isBlank()) values.add(v.trim());
			}
			java.util.List<org.springframework.security.core.GrantedAuthority> out = new java.util.ArrayList<>();
			for (String v : values) {
				out.add(new org.springframework.security.core.authority.SimpleGrantedAuthority(
						v.startsWith("ROLE_") ? v : "ROLE_" + v));
			}
			return out;
		});
		return delegate;
	}
}
