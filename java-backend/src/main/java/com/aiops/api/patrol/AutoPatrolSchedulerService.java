package com.aiops.api.patrol;

import com.aiops.api.domain.patrol.AutoPatrolEntity;
import com.aiops.api.domain.patrol.AutoPatrolRepository;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.TaskScheduler;
import org.springframework.scheduling.support.CronTrigger;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ScheduledFuture;

/**
 * Dynamic registration layer over Spring's {@link TaskScheduler}. Each Auto-Patrol
 * gets its own {@link ScheduledFuture} keyed by patrolId; create/update/delete
 * on the patrol entity must call {@link #refresh(Long)} so the scheduler stays
 * in sync with DB state.
 *
 * <p>Phase 5-minimal:
 *   - Schedule mode: register {@link CronTrigger} from {@code cron_expr}.
 *   - Once mode: schedule a one-shot at {@code scheduled_at} (cleared after fire).
 *   - Event mode: NOT scheduled here (alarm-driven, not implemented in this phase).
 *   - Inactive patrols (or status != "active") are skipped.
 */
@Slf4j
@Service
public class AutoPatrolSchedulerService {

	private final TaskScheduler taskScheduler;
	private final AutoPatrolRepository patrolRepo;
	private final AutoPatrolExecutor executor;

	private final Map<Long, ScheduledFuture<?>> activeJobs = new ConcurrentHashMap<>();

	public AutoPatrolSchedulerService(TaskScheduler taskScheduler,
	                                  AutoPatrolRepository patrolRepo,
	                                  AutoPatrolExecutor executor) {
		this.taskScheduler = taskScheduler;
		this.patrolRepo = patrolRepo;
		this.executor = executor;
	}

	/**
	 * On boot, scan all patrols and register active schedule/once ones.
	 * Idempotent: a stale process restart won't fire the past-due once jobs
	 * (we only schedule if scheduled_at is still in the future).
	 */
	@PostConstruct
	public void init() {
		List<AutoPatrolEntity> all = patrolRepo.findAll();
		int registered = 0;
		for (AutoPatrolEntity p : all) {
			if (Boolean.TRUE.equals(p.getIsActive()) && register(p)) {
				registered++;
			}
		}
		log.info("AutoPatrolSchedulerService bootstrap: {} active patrols registered (of {} total)", registered, all.size());
	}

	/**
	 * Re-read patrol from DB and reconcile its scheduled state. Call this from
	 * AutoPatrolController on create/update/delete and from the toggle-active path.
	 *
	 * <p>If the patrol was deleted (DB miss), the existing future is cancelled.
	 */
	public void refresh(Long patrolId) {
		unregister(patrolId);
		patrolRepo.findById(patrolId).ifPresent(p -> {
			if (Boolean.TRUE.equals(p.getIsActive())) {
				register(p);
			}
		});
	}

	/** Register one patrol; returns true if successfully scheduled. */
	private boolean register(AutoPatrolEntity p) {
		String mode = p.getTriggerMode();
		if ("schedule".equals(mode)) {
			String cron = p.getCronExpr();
			if (cron == null || cron.isBlank()) {
				log.warn("patrol id={} trigger_mode=schedule but cron_expr is empty; skip", p.getId());
				return false;
			}
			try {
				CronTrigger trigger = new CronTrigger(cron);
				ScheduledFuture<?> future = taskScheduler.schedule(
						() -> safeExecute(p.getId()), trigger);
				activeJobs.put(p.getId(), future);
				log.info("patrol id={} scheduled cron='{}'", p.getId(), cron);
				return true;
			} catch (IllegalArgumentException ex) {
				log.warn("patrol id={} invalid cron '{}': {}", p.getId(), cron, ex.getMessage());
				return false;
			}
		}
		if ("once".equals(mode)) {
			OffsetDateTime when = p.getScheduledAt();
			if (when == null) {
				log.warn("patrol id={} trigger_mode=once but scheduled_at is null; skip", p.getId());
				return false;
			}
			if (when.isBefore(OffsetDateTime.now())) {
				log.info("patrol id={} once-mode scheduled_at={} is in the past; skip", p.getId(), when);
				return false;
			}
			Date runAt = Date.from(when.toInstant());
			ScheduledFuture<?> future = taskScheduler.schedule(
					() -> safeExecute(p.getId()), runAt);
			activeJobs.put(p.getId(), future);
			log.info("patrol id={} once-scheduled at={}", p.getId(), when);
			return true;
		}
		// event-mode: not scheduled here (would be triggered by alarm-event handler — Phase 6)
		log.debug("patrol id={} trigger_mode={} not scheduled by cron service", p.getId(), mode);
		return false;
	}

	/** Cancel + remove. Safe to call on a missing key. */
	public void unregister(Long patrolId) {
		ScheduledFuture<?> existing = activeJobs.remove(patrolId);
		if (existing != null) {
			existing.cancel(false);
			log.info("patrol id={} unregistered", patrolId);
		}
	}

	private void safeExecute(Long patrolId) {
		try {
			executor.executePatrol(patrolId);
		} catch (Exception ex) {
			// One bad patrol must NOT crash the scheduler thread.
			log.error("patrol id={} execution threw uncaught exception: {}", patrolId, ex.getMessage(), ex);
		}
	}

	/** Visible for testing / admin debugging. */
	public int activeCount() {
		return activeJobs.size();
	}
}
