package com.aiops.api.api.skill;

import com.aiops.api.domain.event.EventTypeEntity;
import com.aiops.api.domain.event.EventTypeRepository;
import com.aiops.api.domain.patrol.AutoPatrolEntity;
import com.aiops.api.domain.patrol.AutoPatrolRepository;
import com.aiops.api.domain.pipeline.PipelineAutoCheckTriggerEntity;
import com.aiops.api.domain.pipeline.PipelineAutoCheckTriggerRepository;
import com.aiops.api.domain.skill.SkillDocumentEntity;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Map;

/**
 * Phase 11 — materialize a Skill's trigger_config + steps into the existing
 * trigger tables (auto_patrols / pipeline_auto_check_triggers) so the
 * scheduler / event poller fires the per-step pipelines automatically when
 * the skill flips to status=stable. De-publish (status=draft / delete)
 * removes the materialized rows by skill_doc_id.
 *
 * <p>Strategy: ONE row per (skill, step) sharing the skill_doc_id. Multiple
 * rows fire independently — each step's pipeline runs in its own context.
 * SkillRunner aggregation is reserved for explicit UI Run / Test, where
 * coherent step ordering matters; the auto-fire path keeps things simple
 * and reuses existing dispatch.
 */
@Slf4j
@Service
public class SkillMaterializeService {

    private static final TypeReference<List<Map<String, Object>>> JSON_LIST_TYPE = new TypeReference<>() {};
    private static final TypeReference<Map<String, Object>> JSON_MAP_TYPE = new TypeReference<>() {};

    private final ObjectMapper mapper;
    private final AutoPatrolRepository patrolRepo;
    private final PipelineAutoCheckTriggerRepository autoCheckRepo;
    private final EventTypeRepository eventTypeRepo;

    public SkillMaterializeService(ObjectMapper mapper,
                                   AutoPatrolRepository patrolRepo,
                                   PipelineAutoCheckTriggerRepository autoCheckRepo,
                                   EventTypeRepository eventTypeRepo) {
        this.mapper = mapper;
        this.patrolRepo = patrolRepo;
        this.autoCheckRepo = autoCheckRepo;
        this.eventTypeRepo = eventTypeRepo;
    }

    /** Called when status flips draft → stable. */
    @Transactional
    public int materialize(SkillDocumentEntity skill) {
        // Always wipe prior materialization first to keep state idempotent.
        clear(skill);

        Map<String, Object> trig = parseMap(skill.getTriggerConfig());
        String type = String.valueOf(trig.getOrDefault("type", ""));
        if (type.isBlank()) {
            log.warn("skill {} publish: trigger.type missing — nothing to materialize", skill.getSlug());
            return 0;
        }

        List<Map<String, Object>> steps = parseList(skill.getSteps());
        int materialized = 0;
        for (Map<String, Object> step : steps) {
            Number pidNum = (Number) step.get("pipeline_id");
            if (pidNum == null) continue;  // step without bound pipeline — skip silently
            Long pipelineId = pidNum.longValue();
            switch (type) {
                case "system" -> materialized += materializeSystemEvent(skill, pipelineId, trig);
                case "schedule" -> materialized += materializeSchedule(skill, pipelineId, trig);
                case "user" -> materialized += materializeUserRule(skill, pipelineId, step, trig);
                default -> log.warn("skill {} unknown trigger type {}", skill.getSlug(), type);
            }
        }
        log.info("skill {} materialized {} trigger row(s) (type={})", skill.getSlug(), materialized, type);
        return materialized;
    }

    /** Called when status flips stable → draft, or skill deleted. */
    @Transactional
    public int clear(SkillDocumentEntity skill) {
        int n = 0;
        n += patrolRepo.deleteBySkillDocId(skill.getId());
        n += autoCheckRepo.deleteBySkillDocId(skill.getId());
        if (n > 0) {
            log.info("skill {} de-materialized {} trigger row(s)", skill.getSlug(), n);
        }
        return n;
    }

    // ── Per trigger.type strategies ────────────────────────────────────────

    private int materializeSystemEvent(SkillDocumentEntity skill, Long pipelineId, Map<String, Object> trig) {
        String eventType = String.valueOf(trig.getOrDefault("event_type", "")).trim();
        if (eventType.isBlank()) {
            log.warn("skill {} system trigger missing event_type", skill.getSlug());
            return 0;
        }
        PipelineAutoCheckTriggerEntity row = new PipelineAutoCheckTriggerEntity();
        row.setPipelineId(pipelineId);
        row.setEventType(eventType);
        row.setSkillDocId(skill.getId());
        Object filter = trig.get("match_filter");
        if (filter != null) {
            try { row.setMatchFilter(mapper.writeValueAsString(filter)); }
            catch (Exception ignored) {}
        }
        autoCheckRepo.save(row);
        return 1;
    }

    private int materializeSchedule(SkillDocumentEntity skill, Long pipelineId, Map<String, Object> trig) {
        String cron = computeCron(trig);
        if (cron == null) {
            log.warn("skill {} schedule trigger has no cron / interval — skipping", skill.getSlug());
            return 0;
        }
        AutoPatrolEntity p = new AutoPatrolEntity();
        p.setName("[Skill] " + skill.getTitle());
        p.setDescription(skill.getDescription() != null ? skill.getDescription() : "");
        p.setPipelineId(pipelineId);
        p.setSkillDocId(skill.getId());
        p.setTriggerMode("schedule");
        p.setCronExpr(cron);
        p.setIsActive(true);
        p.setKind("shared_alarm");
        p.setAutoCheckDescription("auto-materialized from skill " + skill.getSlug());
        p.setAlarmTitle("[Skill] " + skill.getTitle());
        p.setAlarmSeverity("MEDIUM");
        patrolRepo.save(p);
        return 1;
    }

    /** User-defined rule = scheduled patrol with kind=watch_rule + condition fields
     *  recorded inside notification_template (Phase 9 convention). */
    private int materializeUserRule(SkillDocumentEntity skill, Long pipelineId,
                                     Map<String, Object> step, Map<String, Object> trig) {
        // For now, materialize as a scheduled patrol on a default cron (every 15 min)
        // until full Phase 9 watch_rule integration is wired up. Caller can adjust
        // cron via the trigger UI; this is the safe default.
        AutoPatrolEntity p = new AutoPatrolEntity();
        p.setName("[Rule] " + (trig.get("name") != null ? trig.get("name") : skill.getTitle()));
        p.setDescription("user-defined rule from skill " + skill.getSlug());
        p.setPipelineId(pipelineId);
        p.setSkillDocId(skill.getId());
        p.setTriggerMode("schedule");
        p.setCronExpr("*/15 * * * *");
        p.setIsActive(true);
        p.setKind("watch_rule");
        try {
            p.setNotifyConfig(mapper.writeValueAsString(Map.of(
                    "rule_name", trig.getOrDefault("name", "untitled"),
                    "metric", trig.getOrDefault("metric", ""),
                    "op", trig.getOrDefault("op", ">="),
                    "value", trig.getOrDefault("value", ""),
                    "window", trig.getOrDefault("window", ""),
                    "debounce", trig.getOrDefault("debounce", "")
            )));
        } catch (Exception ignored) {}
        patrolRepo.save(p);
        return 1;
    }

    // ── Helpers ────────────────────────────────────────────────────────────

    private Map<String, Object> parseMap(String json) {
        try {
            return json == null || json.isBlank() ? Map.of() : mapper.readValue(json, JSON_MAP_TYPE);
        } catch (Exception e) {
            return Map.of();
        }
    }

    private List<Map<String, Object>> parseList(String json) {
        try {
            return json == null || json.isBlank() ? List.of() : mapper.readValue(json, JSON_LIST_TYPE);
        } catch (Exception e) {
            return List.of();
        }
    }

    private String computeCron(Map<String, Object> trig) {
        Object cron = trig.get("cron");
        if (cron instanceof String s && !s.isBlank()) return s;
        Number every = (Number) trig.get("every");
        Object unitObj = trig.get("unit");
        if (every == null || unitObj == null) return null;
        int n = every.intValue();
        return switch (String.valueOf(unitObj)) {
            case "minute" -> "*/" + n + " * * * *";
            case "hour"   -> "0 */" + n + " * * *";
            case "day"    -> "0 0 */" + n + " * *";
            default       -> null;
        };
    }
}
