package com.aiops.api.api.skill;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.common.JsonUtils;
import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.skill.SkillDocumentEntity;
import com.aiops.api.domain.skill.SkillDocumentRepository;
import com.aiops.api.domain.skill.SkillRunEntity;
import com.aiops.api.domain.skill.SkillRunRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Sinks;
import reactor.core.scheduler.Schedulers;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Skill-run orchestrator.
 *
 * <p>Phase 11-C → split 2026-05-23 (Phase 12 OOP refactor) into three
 * services that each own one concern:
 * <ul>
 *   <li>{@code SkillRunnerService} (this) — flow control: parse steps,
 *       iterate them, emit SSE events via the {@link RunEvent} record,
 *       wire confirm-gate, persist {@link SkillRunEntity}.</li>
 *   <li>{@link SkillStepExecutor} — runs one step's pipeline through the
 *       sidecar and shapes the result map.</li>
 *   <li>{@link SkillAlarmEmitter} — writes an alarm row when a patrol
 *       step triggers; counters + dedup + ExecutionLog cascade live there.</li>
 * </ul>
 *
 * <p>Per E5 (user decision): steps don't short-circuit on failure — every
 * step runs regardless of upstream verdict, so SummaryReport surfaces all
 * findings at once.
 *
 * <p>Sandbox flag ({@code is_test}) flows through to {@link SkillRunEntity}
 * so stats roll-ups can exclude test runs.
 */
@Slf4j
@Service
public class SkillRunnerService {

	private static final TypeReference<Map<String, Object>> JSON_MAP_TYPE = new TypeReference<>() {};

	private final SkillDocumentRepository skillRepo;
	private final SkillRunRepository runRepo;
	private final ObjectMapper mapper;
	private final SkillStepExecutor stepExecutor;
	private final SkillAlarmEmitter alarmEmitter;

	public SkillRunnerService(SkillDocumentRepository skillRepo,
	                          SkillRunRepository runRepo,
	                          ObjectMapper mapper,
	                          SkillStepExecutor stepExecutor,
	                          SkillAlarmEmitter alarmEmitter) {
		this.skillRepo = skillRepo;
		this.runRepo = runRepo;
		this.mapper = mapper;
		this.stepExecutor = stepExecutor;
		this.alarmEmitter = alarmEmitter;
	}

	/** Snapshot of alarm-emit activity. Consumed by SystemMonitorAliasController.
	 *  Delegates to {@link SkillAlarmEmitter#stats()} so the monitor wiring
	 *  doesn't change. */
	public Map<String, Object> alarmEmitStats() {
		return alarmEmitter.stats();
	}

	/** Reactive stream of SSE-shaped events; controller bridges into SseEmitter. */
	public Flux<RunEvent> run(String slug,
	                          Map<String, Object> triggerPayload,
	                          boolean isTest,
	                          AuthPrincipal caller) {
		return run(slug, triggerPayload, isTest, caller, null);
	}

	/**
	 * v6.1 (2026-05-20): triggeredBy override for system / scheduler paths.
	 * When null, falls back to the legacy "user_test" / "manual" derivation
	 * based on isTest. Pass "system" / "system_schedule" / "system_event"
	 * from the new java-scheduler skill trigger pathways so manual vs
	 * automated runs are distinguishable in skill_runs.
	 */
	public Flux<RunEvent> run(String slug,
	                          Map<String, Object> triggerPayload,
	                          boolean isTest,
	                          AuthPrincipal caller,
	                          String triggeredByOverride) {
		SkillDocumentEntity skill = skillRepo.findBySlug(slug).orElse(null);
		if (skill == null) {
			return Flux.just(RunEvent.error("skill not found: " + slug));
		}

		Sinks.Many<RunEvent> sink = Sinks.many().unicast().onBackpressureBuffer();

		// Fire-and-forget the actual execution on the elastic scheduler so we
		// can return the Flux immediately. Each step's sidecar call is sync
		// (block on the Mono) — keeps the per-step ordering explicit.
		Flux.fromIterable(JsonUtils.parseListOfObjects(mapper, skill.getSteps()))
				.publishOn(Schedulers.boundedElastic())
				.doOnSubscribe(s -> {
					SkillRunEntity run = createRunRow(skill.getId(), triggerPayload, isTest, triggeredByOverride);
					sink.tryEmitNext(RunEvent.start(skill.getSlug(), run.getId(), JsonUtils.parseListOfObjects(mapper, skill.getSteps()).size()));
					runWithSink(skill, run, triggerPayload, sink, caller);
				})
				.subscribe();

		return sink.asFlux();
	}

	private void runWithSink(SkillDocumentEntity skill,
	                         SkillRunEntity run,
	                         Map<String, Object> triggerPayload,
	                         Sinks.Many<RunEvent> sink,
	                         AuthPrincipal caller) {
		long started = System.currentTimeMillis();
		List<Map<String, Object>> steps = JsonUtils.parseListOfObjects(mapper, skill.getSteps());
		List<Map<String, Object>> stepResults = new ArrayList<>();

		// Phase 11 v2 — CONFIRM step (optional gate). If present and fails,
		// skip the entire CHECKLIST and mark run "skipped_by_confirm" so
		// downstream materializers don't write an alarm.
		Map<String, Object> confirmConfig = JsonUtils.parseObject(mapper, skill.getConfirmCheck());
		boolean skipChecklist = false;
		Map<String, Object> confirmResult = null;
		if (!confirmConfig.isEmpty()) {
			Number cpId = (Number) confirmConfig.get("pipeline_id");
			Long confirmPipelineId = cpId != null ? cpId.longValue() : null;
			sink.tryEmitNext(RunEvent.confirmStart());
			if (confirmPipelineId == null) {
				confirmResult = stepExecutor.stepResultPending("confirm", "no confirm pipeline bound");
			} else {
				// 2026-06-26: forward skill id + run.triggered_by so the
				// per-step execution_logs row carries the same provenance
				// as the parent skill_runs row (previously skill_id=-1 /
				// triggered_by='user' on every system_event dispatch).
				confirmResult = stepExecutor.runOneStep("confirm", confirmPipelineId, triggerPayload, caller,
						skill.getId(), run.getTriggeredBy());
			}
			sink.tryEmitNext(RunEvent.confirmDone(confirmResult));
			boolean mustPass = !Boolean.FALSE.equals(confirmConfig.get("must_pass"));
			String confirmStatus = String.valueOf(confirmResult.get("status"));
			if (mustPass && !"pass".equals(confirmStatus)) {
				skipChecklist = true;
			}
		}

		if (!skipChecklist) {
			for (Map<String, Object> step : steps) {
				String stepId = String.valueOf(step.get("id"));
				Number pipelineIdNum = (Number) step.get("pipeline_id");
				Long pipelineId = pipelineIdNum != null ? pipelineIdNum.longValue() : null;

				sink.tryEmitNext(RunEvent.stepStart(stepId));

				Map<String, Object> stepResult;
				if (pipelineId == null) {
					stepResult = stepExecutor.stepResultPending(stepId, "no pipeline bound");
				} else {
					stepResult = stepExecutor.runOneStep(stepId, pipelineId, triggerPayload, caller,
							skill.getId(), run.getTriggeredBy());
				}
				stepResults.add(stepResult);
				sink.tryEmitNext(RunEvent.stepDone(stepResult));
			}
		}

		run.setStatus(skipChecklist ? "skipped_by_confirm" : "completed");
		run.setFinishedAt(OffsetDateTime.now());
		run.setDurationMs((int) (System.currentTimeMillis() - started));
		try {
			// Persist confirm result alongside step_results for replay UI.
			Map<String, Object> persisted = new HashMap<>();
			persisted.put("steps", stepResults);
			if (confirmResult != null) persisted.put("confirm", confirmResult);
			run.setStepResults(mapper.writeValueAsString(persisted));
		} catch (JsonProcessingException e) {
			run.setStepResults("[]");
		}
		runRepo.save(run);

		// Phase 11-D — refresh stats on the skill (excludes test runs from
		// counters; test runs still recorded for historical replay but
		// mustn't pollute marketplace metrics).
		if (Boolean.FALSE.equals(run.getIsTest())) {
			updateSkillStats(skill, run);
		}

		// v30.13 (2026-05-17) — alarm-emit chain. SkillRunner is the only
		// place that knows "step_check.pass=true + skill stage=patrol" → an
		// alarm row should exist. Without this, Alarm Center is permanently
		// empty even when patrol skills run and detect anomalies.
		try {
			AlarmEntity alarm = alarmEmitter.emitIfTriggered(
					skill, run, triggerPayload, confirmResult, stepResults, skipChecklist);
			if (alarm != null) {
				sink.tryEmitNext(RunEvent.alarmCreated(alarm));
			}
			// 2026-06-27 (V60): emitIfTriggered sets run.alarmSkippedReason
			// when guards reject — persist that so the Patrol Activity UI
			// can explain "skill ran, no alarm — why?". The earlier save()
			// above happened before guards ran.
			runRepo.save(run);
		} catch (RuntimeException ex) {  // never let alarm-emit fail the main run
			// RuntimeException catches WebClient errors + JPA + NPE bugs in
			// the emit chain. Checked exceptions (none expected here) bubble.
			log.warn("skill {} run {} alarm-emit failed: {}",
					skill.getSlug(), run.getId(), ex.toString());
		}

		sink.tryEmitNext(RunEvent.done(run.getId(), stepResults));
		sink.tryEmitComplete();
	}

	// ── Persistence helpers ─────────────────────────────────────────────────

	@Transactional
	SkillRunEntity createRunRow(Long skillId, Map<String, Object> payload, boolean isTest) {
		return createRunRow(skillId, payload, isTest, null);
	}

	SkillRunEntity createRunRow(Long skillId, Map<String, Object> payload, boolean isTest,
	                            String triggeredByOverride) {
		SkillRunEntity r = new SkillRunEntity();
		r.setSkillId(skillId);
		r.setIsTest(isTest);
		// v6.1: explicit override for system / scheduler triggered runs.
		String tb = (triggeredByOverride != null && !triggeredByOverride.isBlank())
				? triggeredByOverride
				: (isTest ? "user_test" : "manual");
		r.setTriggeredBy(tb);
		try {
			r.setTriggerPayload(mapper.writeValueAsString(payload != null ? payload : Map.of()));
		} catch (JsonProcessingException e) {
			r.setTriggerPayload("{}");
		}
		return runRepo.save(r);
	}

	@Transactional
	void updateSkillStats(SkillDocumentEntity skill, SkillRunEntity lastRun) {
		try {
			Map<String, Object> stats;
			try {
				stats = new HashMap<>(skill.getStats() == null || skill.getStats().isBlank()
						? Map.of()
						: mapper.readValue(skill.getStats(), JSON_MAP_TYPE));
			} catch (JsonProcessingException e) {
				stats = new HashMap<>();
			}
			int prevTotal = stats.get("runs_total") instanceof Number n ? n.intValue() : 0;
			stats.put("runs_total", prevTotal + 1);
			stats.put("last_run_at", lastRun.getTriggeredAt() != null
					? lastRun.getTriggeredAt().toString() : OffsetDateTime.now().toString());

			// runs_30d — count via repo query
			OffsetDateTime since = OffsetDateTime.now().minusDays(30);
			long runs30d = runRepo.countNonTestSince(skill.getId(), since);
			stats.put("runs_30d", runs30d);

			skill.setStats(mapper.writeValueAsString(stats));
			skillRepo.save(skill);
		} catch (RuntimeException | JsonProcessingException e) {
			// JsonProcessingException for writeValueAsString failure, plus
			// RuntimeException for skillRepo.save (JPA exceptions); stats are
			// non-critical so never break the main run path.
			log.warn("skill {} stats update failed: {}", skill.getSlug(), e.toString());
		}
	}

	// ── Small parsing helpers ──────────────────────────────────────────────


	// ── Wire format ────────────────────────────────────────────────────────

	/** Wire-format: SSE events the controller renders. */
	public record RunEvent(String type, Map<String, Object> data) {
		static RunEvent start(String slug, Long runId, int stepCount) {
			return new RunEvent("run_start", Map.of("slug", slug, "run_id", runId, "step_count", stepCount));
		}
		static RunEvent stepStart(String stepId) {
			return new RunEvent("step_start", Map.of("step_id", stepId));
		}
		static RunEvent stepDone(Map<String, Object> result) {
			return new RunEvent("step_done", result);
		}
		static RunEvent confirmStart() {
			return new RunEvent("confirm_start", Map.of());
		}
		static RunEvent confirmDone(Map<String, Object> result) {
			return new RunEvent("confirm_done", result);
		}
		static RunEvent done(Long runId, List<Map<String, Object>> stepResults) {
			return new RunEvent("done", Map.of("run_id", runId, "step_results", stepResults));
		}
		static RunEvent error(String message) {
			return new RunEvent("error", Map.of("message", message));
		}
		/** v30.13 (2026-05-17) — alarm-emit notification so UI can refresh
		 *  Alarm Center without polling. Carries the new alarm id + summary
		 *  fields, not the full entity (avoid JPA-Jackson cycles). */
		static RunEvent alarmCreated(AlarmEntity a) {
			Map<String, Object> data = new HashMap<>();
			data.put("alarm_id", a.getId());
			data.put("severity", a.getSeverity());
			data.put("title", a.getTitle());
			data.put("equipment_id", a.getEquipmentId());
			data.put("skill_id", a.getSkillId());
			return new RunEvent("alarm_created", data);
		}
	}
}
