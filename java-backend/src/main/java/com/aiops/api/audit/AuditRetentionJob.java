package com.aiops.api.audit;

import com.aiops.api.config.AiopsProperties;
import com.aiops.api.domain.audit.AuditLogRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;

/**
 * Deletes audit log entries older than {@code aiops.audit.retention-days}.
 * Runs daily at 03:15 server time.
 */
@Slf4j
@Component
public class AuditRetentionJob {

	private final AuditLogRepository repository;
	private final AiopsProperties props;

	public AuditRetentionJob(AuditLogRepository repository, AiopsProperties props) {
		this.repository = repository;
		this.props = props;
	}

	@Scheduled(cron = "0 15 3 * * *")
	@Transactional
	public void cleanup() {
		int days = props.audit().retentionDays();
		OffsetDateTime cutoff = OffsetDateTime.now().minusDays(days);
		int deleted = repository.deleteOlderThan(cutoff);
		log.info("Audit retention: deleted {} entries older than {} days (cutoff {})", deleted, days, cutoff);
	}
}
