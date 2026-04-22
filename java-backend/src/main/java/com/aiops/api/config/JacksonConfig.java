package com.aiops.api.config;

import com.fasterxml.jackson.databind.MapperFeature;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import org.springframework.boot.autoconfigure.jackson.Jackson2ObjectMapperBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Phase 2 API-parity:
 *   - Output snake_case on every response (match old Python FastAPI).
 *   - Still accept camelCase on input (Python sidecar + legacy callers).
 */
@Configuration
public class JacksonConfig {

	@Bean
	public Jackson2ObjectMapperBuilderCustomizer snakeCaseCustomizer() {
		return builder -> builder
				.propertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
				.featuresToEnable(MapperFeature.ACCEPT_CASE_INSENSITIVE_PROPERTIES);
	}
}
