package com.aiops.api.config;

import com.aiops.api.audit.AuditInterceptor;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class WebMvcConfig implements WebMvcConfigurer {

	private final AuditInterceptor auditInterceptor;

	public WebMvcConfig(AuditInterceptor auditInterceptor) {
		this.auditInterceptor = auditInterceptor;
	}

	@Override
	public void addInterceptors(InterceptorRegistry registry) {
		registry.addInterceptor(auditInterceptor).addPathPatterns("/api/**");
	}
}
