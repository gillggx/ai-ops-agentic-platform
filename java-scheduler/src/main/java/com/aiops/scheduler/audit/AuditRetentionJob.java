package com.aiops.scheduler.audit;

import com.aiops.api.config.AiopsProperties;
import com.aiops.api.domain.audit.AuditLogRepository;
import com.aiops.scheduler.lock.DistributedLockService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.OffsetDateTime;

/**
 * Deletes audit log entries older than {@code aiops.audit.retention-days}.
 * Runs daily at 03:15 server time.
 *
 * <p>Phase 2 (project-restructure): moved from {@code java-backend
 * com.aiops.api.audit} into the new java-scheduler module so the API
 * service no longer carries any {@code @Scheduled} responsibilities.
 * Repository + properties bean are reused via the gradle project
 * dependency.
 */
@Slf4j
@Component
public class AuditRetentionJob {

	private final AuditLogRepository repository;
	private final AiopsProperties props;
	private final DistributedLockService lockService;

	public AuditRetentionJob(AuditLogRepository repository,
	                         AiopsProperties props,
	                         DistributedLockService lockService) {
		this.repository = repository;
		this.props = props;
		this.lockService = lockService;
	}

	@Scheduled(cron = "0 15 3 * * *")
	public void cleanup() {
		// Phase 3 — only one scheduler pod per fire. TTL 10min covers worst-
		// case retention sweep across multi-million audit rows.
		lockService.runWithLock("audit_retention", Duration.ofMinutes(10), this::doCleanup);
	}

	@Transactional
	void doCleanup() {
		int days = props.audit().retentionDays();
		OffsetDateTime cutoff = OffsetDateTime.now().minusDays(days);
		int deleted = repository.deleteOlderThan(cutoff);
		log.info("Audit retention: deleted {} entries older than {} days (cutoff {})", deleted, days, cutoff);
	}
}
