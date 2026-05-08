package com.aiops.scheduler.patrol;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.TaskScheduler;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;

/**
 * Single shared {@link TaskScheduler} bean used by:
 *   - {@code AuditRetentionJob} (existing daily job, was using the
 *     auto-configured TaskScheduler before this bean existed).
 *   - {@link AutoPatrolSchedulerService} (Phase 5) — registers one
 *     {@code ScheduledFuture} per active patrol with cron / once timing.
 *
 * <p>Pool size = 4 covers typical workload (one patrol fires at a time, the
 * actual scope-expansion + sidecar call is per-target sequential inside the
 * patrol callback).
 */
@Configuration
public class SchedulerConfig {

	@Bean
	public TaskScheduler taskScheduler() {
		ThreadPoolTaskScheduler s = new ThreadPoolTaskScheduler();
		s.setPoolSize(4);
		s.setThreadNamePrefix("aiops-sched-");
		s.setWaitForTasksToCompleteOnShutdown(false);
		s.setRemoveOnCancelPolicy(true);
		s.initialize();
		return s;
	}
}
