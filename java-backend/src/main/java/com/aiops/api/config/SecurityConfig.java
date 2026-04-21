package com.aiops.api.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

/**
 * Phase 0 security:
 *  - CORS on, CSRF off (API-only)
 *  - Actuator health/info public; everything else currently permit-all.
 *  - Phase 2 will replace with JWT resource server + @PreAuthorize.
 */
@Configuration
public class SecurityConfig {

	@Bean
	public SecurityFilterChain filterChain(HttpSecurity http, UrlBasedCorsConfigurationSource cors) throws Exception {
		http
				.cors(c -> c.configurationSource(cors))
				.csrf(AbstractHttpConfigurer::disable)
				.httpBasic(AbstractHttpConfigurer::disable)
				.formLogin(AbstractHttpConfigurer::disable)
				.sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
				.authorizeHttpRequests(a -> a
						.requestMatchers("/actuator/health/**", "/actuator/info").permitAll()
						.anyRequest().permitAll()   // Phase 0: open; Phase 2 flips to .authenticated()
				);
		return http.build();
	}

	@Bean
	public PasswordEncoder passwordEncoder() {
		return new BCryptPasswordEncoder(12);
	}
}
