package com.aiops.api;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;

/**
 * Phase 2 (project-restructure): {@code @EnableScheduling} removed from the
 * API service — all {@code @Scheduled} jobs live in the new java-scheduler
 * module ({@link com.aiops.scheduler.AiopsSchedulerApplication}). The API
 * service reaches the scheduler over HTTP via {@code SchedulerHttpClient}.
 * {@code @EnableAsync} stays — non-scheduling async helpers are still useful
 * inside the API JVM (e.g. fire-and-forget audit writes).
 */
@SpringBootApplication
@EnableAsync
public class AiopsApiApplication {

	public static void main(String[] args) {
		SpringApplication.run(AiopsApiApplication.class, args);
	}
}
