package com.aiops.scheduler;

import com.aiops.api.config.AiopsProperties;
import com.aiops.api.config.JacksonConfig;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.domain.EntityScan;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Import;
import org.springframework.data.jpa.repository.config.EnableJpaRepositories;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * Phase 2 (project-restructure) — split Java scheduler service.
 *
 * <p>Runs every {@code @Scheduled} job and the patrol/event execution
 * machinery that used to share a JVM with the REST API. Component
 * scanning is deliberately narrow:
 * <ul>
 *   <li>{@code com.aiops.scheduler}    — this module's own code</li>
 *   <li>{@code com.aiops.api.domain}   — entities + JPA repos (shared
 *       with java-backend; pulled in via gradle project dep)</li>
 *   <li>{@code com.aiops.api.sidecar}  — SimulatorClient + Python
 *       sidecar HTTP config used by EventPoller / AutoPatrolExecutor</li>
 * </ul>
 *
 * <p>Other API-side packages ({@code com.aiops.api.api},
 * {@code com.aiops.api.auth}, REST controllers, security filters) are
 * deliberately NOT scanned. The scheduler only exposes a minimal
 * internal HTTP surface ({@code /internal/scheduler/*}) for the API
 * service to call.
 */
@SpringBootApplication(scanBasePackages = {
		"com.aiops.scheduler",
		"com.aiops.api.sidecar",                // PythonSidecarConfig (WebClient + token bean)
		"com.aiops.api.domain.notification",    // NotificationDispatchService — used by AutoPatrolExecutor
})
@EnableConfigurationProperties(AiopsProperties.class)
@Import(JacksonConfig.class)                    // SNAKE_CASE Jackson config
@EnableJpaRepositories(basePackages = "com.aiops.api.domain")
@EntityScan(basePackages = "com.aiops.api.domain")
@EnableScheduling
public class AiopsSchedulerApplication {
	public static void main(String[] args) {
		SpringApplication.run(AiopsSchedulerApplication.class, args);
	}
}
