package com.aiops.api.api.agentepisode;

import com.aiops.api.common.ApiException;
import com.aiops.api.common.JsonUtils;
import com.aiops.api.domain.agentepisode.AgentEpisodeEntity;
import com.aiops.api.domain.agentepisode.AgentEpisodeRepository;
import com.aiops.api.domain.agentepisode.AgentStepEntity;
import com.aiops.api.domain.agentepisode.AgentStepRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Agent observability write path (V69). The sidecar's EpisodeRecorder is
 * fire-and-forget + fail-open, so every method here is designed to be
 * forgiving: upserts are idempotent by episode_key, and step batches for an
 * unknown episode auto-create a stub episode (a lost create must never make
 * the whole behavioural stream unrecordable).
 *
 * <p>Spec: docs/MULTI_AGENT_OBSERVABILITY_SPEC.md §4.
 */
@Service
public class AgentEpisodeService {

    private final AgentEpisodeRepository episodes;
    private final AgentStepRepository steps;
    private final ObjectMapper mapper;

    public AgentEpisodeService(AgentEpisodeRepository episodes,
                               AgentStepRepository steps,
                               ObjectMapper mapper) {
        this.episodes = episodes;
        this.steps = steps;
        this.mapper = mapper;
    }

    /** Idempotent create-or-update by episode_key. */
    @Transactional
    public AgentEpisodeEntity upsert(String episodeKey, Long userId,
                                     String instruction, String startedAtIso,
                                     String triggerSource) {
        if (episodeKey == null || episodeKey.isBlank()) {
            throw ApiException.badRequest("episode_key required");
        }
        AgentEpisodeEntity ep = episodes.findByEpisodeKey(episodeKey)
                .orElseGet(AgentEpisodeEntity::new);
        if (ep.getId() == null) {
            ep.setEpisodeKey(episodeKey);
            ep.setStartedAt(parseTs(startedAtIso));
        }
        if (userId != null) ep.setUserId(userId);
        if (instruction != null && !instruction.isBlank()) ep.setInstruction(instruction);
        // 只在首次（尚無值）寫入 — resume 呼叫不清掉原始來源
        if (triggerSource != null && !triggerSource.isBlank() && ep.getTriggerSource() == null) {
            ep.setTriggerSource(triggerSource);
        }
        return episodes.save(ep);
    }

    /**
     * Batch-append behavioural steps. Unknown episode_key auto-creates a stub
     * (fail-open on the write side mirrors the recorder's fail-open send side).
     * Returns the number of rows written.
     */
    @Transactional
    public int appendSteps(String episodeKey, List<Map<String, Object>> batch) {
        if (batch == null || batch.isEmpty()) return 0;
        AgentEpisodeEntity ep = episodes.findByEpisodeKey(episodeKey)
                .orElseGet(() -> upsert(episodeKey, null, "", null, null));
        List<AgentStepEntity> rows = new ArrayList<>(batch.size());
        for (Map<String, Object> s : batch) {
            String agent = str(s.get("agent"));
            String eventType = str(s.get("event_type"));
            if (agent == null || eventType == null) continue; // skip malformed, keep the rest
            AgentStepEntity row = new AgentStepEntity();
            row.setEpisodeId(ep.getId());
            row.setAgent(agent);
            row.setPhaseId(str(s.get("phase_id")));
            row.setEventType(eventType);
            Object payload = s.get("payload");
            row.setPayload(payload == null ? null
                    : (payload instanceof String ps ? ps : JsonUtils.safeWrite(mapper, payload)));
            row.setInputTokens(intOrNull(s.get("input_tokens")));
            row.setOutputTokens(intOrNull(s.get("output_tokens")));
            row.setCacheRead(intOrNull(s.get("cache_read")));
            row.setLatencyMs(intOrNull(s.get("latency_ms")));
            row.setTs(parseTs(str(s.get("ts"))));
            rows.add(row);
        }
        steps.saveAll(rows);
        return rows.size();
    }

    /** Finalize the episode envelope; recomputes divergence. */
    @Transactional
    public AgentEpisodeEntity finalizeEpisode(String episodeKey, Map<String, Object> body) {
        AgentEpisodeEntity ep = episodes.findByEpisodeKey(episodeKey)
                .orElseThrow(() -> ApiException.notFound("episode " + episodeKey));
        if (body.get("status") != null) ep.setStatus(str(body.get("status")));
        if (body.get("plan_json") != null) ep.setPlanJson(jsonOrString(body.get("plan_json")));
        if (body.get("self_assessment") != null) ep.setSelfAssessment(jsonOrString(body.get("self_assessment")));
        if (body.get("cost_json") != null) ep.setCostJson(jsonOrString(body.get("cost_json")));
        if (body.get("trace_file") != null) ep.setTraceFile(str(body.get("trace_file")));
        ep.setFinishedAt(body.get("finished_at") != null
                ? parseTs(str(body.get("finished_at"))) : OffsetDateTime.now());
        ep.setDivergence(deriveDivergence(ep));
        return episodes.save(ep);
    }

    /**
     * Append one user-feedback entry ({stage, sentiment, text}) and re-derive
     * divergence. Called from the internal API (sidecar) and, in Step 6, from
     * the user-facing feedback endpoint via proxy.
     */
    @Transactional
    public AgentEpisodeEntity appendFeedback(String episodeKey, String stage,
                                             String sentiment, String text) {
        AgentEpisodeEntity ep = episodes.findByEpisodeKey(episodeKey)
                .orElseThrow(() -> ApiException.notFound("episode " + episodeKey));
        if (sentiment == null || sentiment.isBlank()) {
            throw ApiException.badRequest("sentiment required (accept|edit|reject)");
        }
        List<Map<String, Object>> fb = JsonUtils.parseListOfObjects(mapper, ep.getUserFeedback());
        fb = new ArrayList<>(fb);
        fb.add(Map.of(
                "stage", stage == null ? "delivery" : stage,
                "sentiment", sentiment,
                "text", text == null ? "" : text,
                "ts", OffsetDateTime.now().toString()));
        ep.setUserFeedback(JsonUtils.safeWrite(mapper, fb));
        ep.setDivergence(deriveDivergence(ep));
        return episodes.save(ep);
    }

    /**
     * Divergence = the system thought it succeeded but the user rejected the
     * delivery — the highest-value learning signal (spec §2 Episode layer).
     */
    private boolean deriveDivergence(AgentEpisodeEntity ep) {
        Map<String, Object> self = JsonUtils.parseObject(mapper, ep.getSelfAssessment());
        boolean selfOk = Boolean.TRUE.equals(self.get("ok"));
        if (!selfOk) return false;
        for (Map<String, Object> f : JsonUtils.parseListOfObjects(mapper, ep.getUserFeedback())) {
            if ("reject".equals(f.get("sentiment"))
                    && "delivery".equals(f.getOrDefault("stage", "delivery"))) {
                return true;
            }
        }
        return false;
    }

    private OffsetDateTime parseTs(String iso) {
        if (iso == null || iso.isBlank()) return OffsetDateTime.now();
        try {
            return OffsetDateTime.parse(iso);
        } catch (DateTimeParseException ex) {
            return OffsetDateTime.now();
        }
    }

    private String jsonOrString(Object o) {
        return o instanceof String s ? s : JsonUtils.safeWrite(mapper, o);
    }

    private static String str(Object o) {
        if (o == null) return null;
        String s = String.valueOf(o);
        return s.isBlank() ? null : s;
    }

    private static Integer intOrNull(Object o) {
        if (o == null) return null;
        if (o instanceof Number n) return n.intValue();
        try {
            return Integer.parseInt(String.valueOf(o));
        } catch (NumberFormatException ex) {
            return null;
        }
    }
}
