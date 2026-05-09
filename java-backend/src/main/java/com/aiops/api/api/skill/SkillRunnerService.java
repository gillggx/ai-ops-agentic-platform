package com.aiops.api.api.skill;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.skill.SkillDocumentEntity;
import com.aiops.api.domain.skill.SkillDocumentRepository;
import com.aiops.api.domain.skill.SkillRunEntity;
import com.aiops.api.domain.skill.SkillRunRepository;
import com.aiops.api.sidecar.PythonSidecarClient;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Sinks;
import reactor.core.scheduler.Schedulers;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Phase 11-C — SkillRunner.
 *
 * <p>Runs all steps of a Skill Document sequentially. Each step has a
 * {@code pipeline_id} pointing to {@code pb_pipelines}; we forward the
 * trigger_payload as inputs to the sidecar's pipeline executor and read
 * the {@code block_step_check} output ({@code pass / value / note}) to
 * decide step pass/fail.
 *
 * <p>Per E5 (user decision): steps don't short-circuit on failure — every
 * step runs regardless of upstream verdict, so SummaryReport surfaces
 * all findings at once.
 *
 * <p>Sandbox flag ({@code is_test}) flows through to {@link SkillRunEntity}
 * so stats roll-ups can exclude test runs.
 */
@Slf4j
@Service
public class SkillRunnerService {

    private static final TypeReference<List<Map<String, Object>>> JSON_LIST_TYPE = new TypeReference<>() {};
    private static final TypeReference<Map<String, Object>> JSON_MAP_TYPE = new TypeReference<>() {};

    private final SkillDocumentRepository skillRepo;
    private final SkillRunRepository runRepo;
    private final PipelineRepository pipelineRepo;
    private final PythonSidecarClient sidecar;
    private final ObjectMapper mapper;

    public SkillRunnerService(SkillDocumentRepository skillRepo,
                              SkillRunRepository runRepo,
                              PipelineRepository pipelineRepo,
                              PythonSidecarClient sidecar,
                              ObjectMapper mapper) {
        this.skillRepo = skillRepo;
        this.runRepo = runRepo;
        this.pipelineRepo = pipelineRepo;
        this.sidecar = sidecar;
        this.mapper = mapper;
    }

    /** Reactive stream of SSE-shaped events; controller bridges into SseEmitter. */
    public Flux<RunEvent> run(String slug,
                              Map<String, Object> triggerPayload,
                              boolean isTest,
                              AuthPrincipal caller) {
        SkillDocumentEntity skill = skillRepo.findBySlug(slug).orElse(null);
        if (skill == null) {
            return Flux.just(RunEvent.error("skill not found: " + slug));
        }

        Sinks.Many<RunEvent> sink = Sinks.many().unicast().onBackpressureBuffer();

        // Fire-and-forget the actual execution on the elastic scheduler so we
        // can return the Flux immediately. Each step's sidecar call is sync
        // (block on the Mono) — keeps the per-step ordering explicit.
        Flux.fromIterable(parseSteps(skill.getSteps()))
                .publishOn(Schedulers.boundedElastic())
                .doOnSubscribe(s -> {
                    SkillRunEntity run = createRunRow(skill.getId(), triggerPayload, isTest);
                    sink.tryEmitNext(RunEvent.start(skill.getSlug(), run.getId(), parseSteps(skill.getSteps()).size()));
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
        List<Map<String, Object>> steps = parseSteps(skill.getSteps());
        List<Map<String, Object>> stepResults = new ArrayList<>();

        for (Map<String, Object> step : steps) {
            String stepId = String.valueOf(step.get("id"));
            Number pipelineIdNum = (Number) step.get("pipeline_id");
            Long pipelineId = pipelineIdNum != null ? pipelineIdNum.longValue() : null;

            sink.tryEmitNext(RunEvent.stepStart(stepId));

            Map<String, Object> stepResult;
            if (pipelineId == null) {
                stepResult = stepResultPending(stepId, "no pipeline bound");
            } else {
                stepResult = runOneStep(stepId, pipelineId, triggerPayload, caller);
            }
            stepResults.add(stepResult);
            sink.tryEmitNext(RunEvent.stepDone(stepResult));
        }

        run.setStatus("completed");
        run.setFinishedAt(OffsetDateTime.now());
        run.setDurationMs((int) (System.currentTimeMillis() - started));
        try {
            run.setStepResults(mapper.writeValueAsString(stepResults));
        } catch (Exception e) {
            run.setStepResults("[]");
        }
        runRepo.save(run);
        sink.tryEmitNext(RunEvent.done(run.getId(), stepResults));
        sink.tryEmitComplete();
    }

    private Map<String, Object> runOneStep(String stepId,
                                            Long pipelineId,
                                            Map<String, Object> payload,
                                            AuthPrincipal caller) {
        long t0 = System.currentTimeMillis();
        try {
            PipelineEntity pe = pipelineRepo.findById(pipelineId).orElse(null);
            if (pe == null) {
                return stepResultError(stepId, "pipeline not found: " + pipelineId);
            }
            String pipelineJson = pe.getPipelineJson();
            if (pipelineJson == null || pipelineJson.isBlank()) {
                return stepResultError(stepId, "pipeline_json empty");
            }
            Map<String, Object> body = new HashMap<>();
            // Sidecar /internal/pipeline/execute expects a parsed JSON, not a string.
            body.put("pipeline_json", mapper.readValue(pipelineJson, JSON_MAP_TYPE));
            body.put("inputs", payload != null ? payload : Map.of());

            @SuppressWarnings({"unchecked", "rawtypes"})
            Map result = sidecar.postJson("/internal/pipeline/execute", body, Map.class, caller)
                    .block(Duration.ofSeconds(60));
            return parseRunResult(stepId, result, System.currentTimeMillis() - t0);
        } catch (Exception ex) {
            log.warn("step {} pipeline {} crashed: {}", stepId, pipelineId, ex.toString());
            return stepResultError(stepId, ex.getClass().getSimpleName() + ": " + ex.getMessage());
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> parseRunResult(String stepId, Map<?, ?> result, long elapsedMs) {
        if (result == null) return stepResultError(stepId, "sidecar returned null");
        String overall = String.valueOf(result.get("status"));
        if (!"success".equals(overall)) {
            return stepResultError(stepId, "pipeline " + overall + ": " + result.get("error_message"));
        }
        Map<String, Object> nodeResults = (Map<String, Object>) result.getOrDefault("node_results", Map.of());
        // Find the block_step_check output. Convention: last node's output port "check".
        Map<String, Object> stepCheck = null;
        for (Map.Entry<String, Object> e : nodeResults.entrySet()) {
            Map<String, Object> nr = (Map<String, Object>) e.getValue();
            Map<String, Object> outputs = (Map<String, Object>) nr.getOrDefault("outputs", Map.of());
            if (outputs.containsKey("check")) {
                stepCheck = (Map<String, Object>) outputs.get("check");
            }
        }
        Map<String, Object> sr = new HashMap<>();
        sr.put("step_id", stepId);
        sr.put("duration_ms", elapsedMs);
        if (stepCheck == null) {
            // Pipeline ran but no step_check output — treat as fail with diagnostic note
            sr.put("status", "fail");
            sr.put("value", "no step_check output");
            sr.put("note", "skill-step pipelines must end in block_step_check");
            return sr;
        }
        // step_check emits a single-row dataframe — extract first row.
        List<Map<String, Object>> rows = (List<Map<String, Object>>) stepCheck.getOrDefault("rows", List.of());
        Map<String, Object> row = rows.isEmpty() ? Map.of() : rows.get(0);
        boolean pass = Boolean.TRUE.equals(row.get("pass"));
        sr.put("status", pass ? "pass" : "fail");
        sr.put("value", String.valueOf(row.getOrDefault("value", "")));
        sr.put("note", String.valueOf(row.getOrDefault("note", "")));
        sr.put("threshold", row.get("threshold"));
        sr.put("operator", row.get("operator"));
        return sr;
    }

    private List<Map<String, Object>> parseSteps(String json) {
        try {
            return mapper.readValue(json == null || json.isBlank() ? "[]" : json, JSON_LIST_TYPE);
        } catch (Exception e) {
            return List.of();
        }
    }

    @Transactional
    SkillRunEntity createRunRow(Long skillId, Map<String, Object> payload, boolean isTest) {
        SkillRunEntity r = new SkillRunEntity();
        r.setSkillId(skillId);
        r.setIsTest(isTest);
        r.setTriggeredBy(isTest ? "user_test" : "manual");
        try {
            r.setTriggerPayload(mapper.writeValueAsString(payload != null ? payload : Map.of()));
        } catch (Exception e) {
            r.setTriggerPayload("{}");
        }
        return runRepo.save(r);
    }

    private Map<String, Object> stepResultError(String stepId, String msg) {
        Map<String, Object> sr = new HashMap<>();
        sr.put("step_id", stepId);
        sr.put("status", "fail");
        sr.put("value", "error");
        sr.put("note", msg);
        return sr;
    }

    private Map<String, Object> stepResultPending(String stepId, String reason) {
        Map<String, Object> sr = new HashMap<>();
        sr.put("step_id", stepId);
        sr.put("status", "skipped");
        sr.put("value", "—");
        sr.put("note", reason);
        return sr;
    }

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
        static RunEvent done(Long runId, List<Map<String, Object>> stepResults) {
            return new RunEvent("done", Map.of("run_id", runId, "step_results", stepResults));
        }
        static RunEvent error(String message) {
            return new RunEvent("error", Map.of("message", message));
        }
    }
}
