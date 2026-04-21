package com.aiops.api.config;

import com.aiops.api.auth.InternalServiceTokenFilter;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.annotation.Order;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

/**
 * Higher-priority {@link SecurityFilterChain} that only matches {@code /internal/**}.
 *
 * <p>On these paths we disable the main JWT filter and instead require a valid
 * {@code X-Internal-Token} via {@link InternalServiceTokenFilter}. This is the
 * auth layer the Python sidecar uses when calling back into Java.
 */
@Configuration
public class InternalSecurityConfig {

	@Bean
	@Order(1)
	public SecurityFilterChain internalFilterChain(HttpSecurity http,
	                                               InternalServiceTokenFilter internalFilter) throws Exception {
		http
				.securityMatcher("/internal/**")
				.csrf(AbstractHttpConfigurer::disable)
				.cors(Customizer.withDefaults())
				.httpBasic(AbstractHttpConfigurer::disable)
				.formLogin(AbstractHttpConfigurer::disable)
				.sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
				.exceptionHandling(e -> e.authenticationEntryPoint((req, res, ex) -> {
					res.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
					res.setContentType("application/json");
					res.getWriter().write(
							"{\"ok\":false,\"error\":{\"code\":\"unauthorized\",\"message\":\"internal token required\"}}");
				}))
				.authorizeHttpRequests(a -> a.anyRequest().authenticated())
				.addFilterBefore(internalFilter, UsernamePasswordAuthenticationFilter.class);
		return http.build();
	}
}
