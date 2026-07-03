package com.aiops.api.api.agentepisode;

import com.aiops.api.common.ApiException;
import com.aiops.api.common.JsonUtils;
import com.aiops.api.domain.agentepisode.AgentEpisodeEntity;
import com.aiops.api.domain.agentepisode.AgentEpisodeRepository;
import com.aiops.api.domain.agentepisode.AgentStepEntity;
import com.aiops.api.domain.agentepisode.AgentStepRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.*;

/**
 * Agent Activity read path (spec MULTI_AGENT_ACTIVITY_UI_SPEC §3). Read-only
 * views over the observability tables for the /agent-activity page:
 *   - list()   : recent builds (picker)
 *   - detail() : one build's episode + ordered steps
 *   - rounds() : trace-style per-round prompt+output (from the BuildTracer JSON
 *                the sidecar wrote) MERGED with the memories each round recalled
 */
@Service
public class AgentActivityService {

    private final AgentEpisodeRepository episodes;
    private final AgentStepRepository steps;
    private final ObjectMapper mapper;

    public AgentActivityService(AgentEpisodeRepository episodes,
                                AgentStepRepository steps, ObjectMapper mapper) {
        this.episodes = episodes;
        this.steps = steps;
        this.mapper = mapper;
    }

    @Transactional(readOnly = true)
    public List<Map<String, Object>> list(int limit) {
        List<AgentEpisodeEntity> rows = episodes.findAllByOrderByIdDesc(
                PageRequest.of(0, Math.max(1, Math.min(limit, 100))));
        List<Map<String, Object>> out = new ArrayList<>();
        for (AgentEpisodeEntity e : rows) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("episode_key", e.getEpisodeKey());
            m.put("instruction", e.getInstruction());
            m.put("status", e.getStatus());
            m.put("divergence", e.isDivergence());
            m.put("step_count", steps.countByEpisodeId(e.getId()));
            m.put("cost", JsonUtils.parseObject(mapper, e.getCostJson()));
            m.put("started_at", e.getStartedAt() == null ? null : e.getStartedAt().toString());
            out.add(m);
        }
        return out;
    }

    @Transactional(readOnly = true)
    public Map<String, Object> detail(String key) {
        AgentEpisodeEntity e = episodes.findByEpisodeKey(key)
                .orElseThrow(() -> ApiException.notFound("episode " + key));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("episode_key", e.getEpisodeKey());
        out.put("instruction", e.getInstruction());
        out.put("status", e.getStatus());
        out.put("divergence", e.isDivergence());
        out.put("self_assessment", JsonUtils.parseObject(mapper, e.getSelfAssessment()));
        out.put("user_feedback", JsonUtils.parseListOfObjects(mapper, e.getUserFeedback()));
        out.put("cost", JsonUtils.parseObject(mapper, e.getCostJson()));
        out.put("plan", JsonUtils.parseListOfObjects(mapper, e.getPlanJson()));
        List<Map<String, Object>> stepList = new ArrayList<>();
        for (AgentStepEntity s : steps.findByEpisodeIdOrderByTsAsc(e.getId())) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("agent", s.getAgent());
            m.put("phase_id", s.getPhaseId());
            m.put("event_type", s.getEventType());
            m.put("payload", JsonUtils.parseObject(mapper, s.getPayload()));
            m.put("ts", s.getTs() == null ? null : s.getTs().toString());
            stepList.add(m);
        }
        out.put("steps", stepList);
        return out;
    }

    /**
     * Trace-style rounds: read the raw BuildTracer JSON (path stored on the
     * episode) for per-round prompt+output, then merge in the memories each
     * (phase,round) recalled from memory_recall steps. This is the "like the
     * original build trace, but prompt shows referenced memory" view (U2/U3).
     *
     * <p>Returns {available:false} when the trace file is missing (sidecar ran
     * with BUILDER_TRACE_DIR off, or file rotated) — the UI falls back to the
     * steps view. Never throws on a missing/parse-broken trace.
     */
    @Transactional(readOnly = true)
    public Map<String, Object> rounds(String key) {
        AgentEpisodeEntity e = episodes.findByEpisodeKey(key)
                .orElseThrow(() -> ApiException.notFound("episode " + key));

        // index recalled memories by (phase_id|round)
        Map<String, List<Map<String, Object>>> recallIdx = new HashMap<>();
        for (AgentStepEntity s : steps.findByEpisodeIdOrderByTsAsc(e.getId())) {
            if (!"memory_recall".equals(s.getEventType())) continue;
            Map<String, Object> p = JsonUtils.parseObject(mapper, s.getPayload());
            Object rec = p.get("recalled");
            Object rnd = p.get("round");
            String k = (s.getPhaseId() == null ? "-" : s.getPhaseId()) + "|" + rnd;
            if (rec instanceof List<?> l) {
                List<Map<String, Object>> rl = new ArrayList<>();
                for (Object o : l) if (o instanceof Map<?, ?> mm) rl.add(JsonUtils.asMap(mm));
                recallIdx.put(k, rl);
            }
        }

        Map<String, Object> out = new LinkedHashMap<>();
        String tracePath = e.getTraceFile();
        List<Map<String, Object>> calls = TraceFileReader.readLlmCalls(mapper, tracePath);
        if (calls == null) {
            out.put("available", false);
            out.put("reason", "trace file not found: " + tracePath);
            out.put("recall_index", recallIdx);   // still useful for the steps view
            return out;
        }
        for (Map<String, Object> c : calls) {
            Object ph = c.get("phase_id");
            Object rnd = c.get("round");
            String k = (ph == null ? "-" : String.valueOf(ph)) + "|" + rnd;
            c.put("recalled", recallIdx.getOrDefault(k, List.of()));
        }
        out.put("available", true);
        out.put("rounds", calls);
        return out;
    }
}
