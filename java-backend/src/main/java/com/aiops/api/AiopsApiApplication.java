package com.aiops.api;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * Phase 2 (project-restructure): business {@code @Scheduled} jobs (patrol,
 * reconcile) live in the java-scheduler module
 * ({@code com.aiops.scheduler.AiopsSchedulerApplication}); the API service
 * reaches the scheduler over HTTP via {@code SchedulerHttpClient}.
 * {@code @EnableAsync} stays — non-scheduling async helpers are still useful
 * inside the API JVM (e.g. fire-and-forget audit writes).
 *
 * <p>W3 (2026-07): {@code @EnableScheduling} re-added for exactly ONE bean —
 * {@link com.aiops.api.api.memory.MemoryLifecycleJanitor}, a daily
 * single-table DB-hygiene sweep over {@code agent_knowledge}. It stays in
 * this JVM (not java-scheduler) because the API service is the sole owner of
 * that table's writes and no cross-service coordination is involved. Any NEW
 * {@code @Scheduled} bean added to this module needs the same justification —
 * default home for jobs remains java-scheduler.
 */
@SpringBootApplication
@EnableAsync
@EnableScheduling
public class AiopsApiApplication {

	public static void main(String[] args) {
		SpringApplication.run(AiopsApiApplication.class, args);
	}
}
