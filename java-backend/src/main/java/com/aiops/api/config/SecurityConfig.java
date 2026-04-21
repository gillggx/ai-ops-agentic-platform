package com.aiops.api.config;

import com.aiops.api.auth.JwtAuthenticationFilter;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
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
	public SecurityFilterChain filterChain(HttpSecurity http,
	                                       UrlBasedCorsConfigurationSource cors,
	                                       AiopsProperties props,
	                                       JwtAuthenticationFilter jwtFilter) throws Exception {
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
								"/api/v1/health"
						).permitAll()
						.anyRequest().authenticated()
				);

		if (props.auth().mode() == AiopsProperties.Auth.Mode.oidc) {
			String issuer = props.oidc().issuer();
			if (issuer != null && !issuer.isBlank()) {
				http.oauth2ResourceServer(o -> o.jwt(j -> j.jwkSetUri(issuer + "/discovery/v2.0/keys")));
			}
		} else {
			http.addFilterBefore(jwtFilter, UsernamePasswordAuthenticationFilter.class);
		}

		return http.build();
	}

	@Bean
	public PasswordEncoder passwordEncoder() {
		return new BCryptPasswordEncoder(12);
	}
}
