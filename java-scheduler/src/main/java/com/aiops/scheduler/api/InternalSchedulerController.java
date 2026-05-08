package com.aiops.scheduler.api;

import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.scheduler.patrol.AutoPatrolExecutor;
import com.aiops.scheduler.patrol.AutoPatrolSchedulerService;
import com.aiops.scheduler.patrol.EventDispatchService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * Phase 2 — internal HTTP surface that aiops-java-api calls into so it
 * doesn't have to inject the scheduler beans directly. Auth is a shared
 * X-Internal-Token (matches the sidecar ↔ Java pattern).
 *
 * <p>Endpoints:
 * <ul>
 *   <li>POST /internal/scheduler/trigger/{patrolId} — synchronous patrol fire</li>
 *   <li>POST /internal/scheduler/sync/{patrolId}    — re-register a patrol's cron after CRUD</li>
 *   <li>POST /internal/scheduler/dispatch-event     — fan out a generated_events row</li>
 *   <li>POST /internal/scheduler/dispatch-alarm     — fan out an alarm to auto_check pipelines</li>
 * </ul>
 *
 * <p>The /trigger response is the {@link AutoPatrolExecutor.PatrolRunResult}
 * record so callers can deep-link to the resulting pb_pipeline_runs row.
 */
@Slf4j
@RestController
@RequestMapping("/internal/scheduler")
public class InternalSchedulerController {

	private final AutoPatrolExecutor patrolExecutor;
	private final AutoPatrolSchedulerService schedulerService;
	private final EventDispatchService dispatchService;
	private final AlarmRepository alarmRepo;
	private final String internalToken;

	public InternalSchedulerController(AutoPatrolExecutor patrolExecutor,
	                                   AutoPatrolSchedulerService schedulerService,
	                                   EventDispatchService dispatchService,
	                                   AlarmRepository alarmRepo,
	                                   @Value("${aiops.scheduler.internal-token:dev-only-do-not-use-in-prod}") String internalToken) {
		this.patrolExecutor = patrolExecutor;
		this.schedulerService = schedulerService;
		this.dispatchService = dispatchService;
		this.alarmRepo = alarmRepo;
		this.internalToken = internalToken;
	}

	@PostMapping("/trigger/{patrolId}")
	public ApiResponse<AutoPatrolExecutor.PatrolRunResult> trigger(@PathVariable Long patrolId,
	                                                               @RequestHeader(value = "X-Internal-Token", required = false) String token) {
		requireToken(token);
		AutoPatrolExecutor.PatrolRunResult result = patrolExecutor.executePatrol(patrolId);
		return ApiResponse.ok(result);
	}

	@PostMapping("/sync/{patrolId}")
	public ApiResponse<Void> syncOne(@PathVariable Long patrolId,
	                                 @RequestHeader(value = "X-Internal-Token", required = false) String token) {
		requireToken(token);
		schedulerService.reconcileOne(patrolId);
		return ApiResponse.ok(null);
	}

	@PostMapping("/dispatch-event")
	public ApiResponse<Void> dispatchEvent(@RequestBody DispatchEventRequest req,
	                                       @RequestHeader(value = "X-Internal-Token", required = false) String token) {
		requireToken(token);
		dispatchService.dispatchGeneratedEvent(req.eventTypeId(), req.mappedParameters());
		return ApiResponse.ok(null);
	}

	@PostMapping("/dispatch-alarm/{alarmId}")
	public ApiResponse<Void> dispatchAlarm(@PathVariable Long alarmId,
	                                       @RequestHeader(value = "X-Internal-Token", required = false) String token) {
		requireToken(token);
		AlarmEntity alarm = alarmRepo.findById(alarmId).orElseThrow(() -> ApiException.notFound("alarm"));
		dispatchService.dispatchAlarm(alarm);
		return ApiResponse.ok(null);
	}

	private void requireToken(String provided) {
		if (provided == null || !provided.equals(internalToken)) {
			throw ApiException.forbidden("invalid X-Internal-Token");
		}
	}

	public record DispatchEventRequest(Long eventTypeId, String mappedParameters) {}
}
