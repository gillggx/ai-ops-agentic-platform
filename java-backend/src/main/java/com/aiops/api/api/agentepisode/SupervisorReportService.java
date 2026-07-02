package com.aiops.api.api.agentepisode;

import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Supervisor v1 read path (spec §5): cross-build aggregates over
 * agent_episodes / agent_steps. REPORT + DRAFTS ONLY — this service never
 * writes anything back; auto-curation is a later phase by design.
 *
 * <p>All queries are read-only native SQL (payload is JSON text; we cast to
 * jsonb for extraction). Called from the internal report endpoint; the
 * rendering to markdown lives in tools/supervisor_report (outside the JVM).
 */
@Service
public class SupervisorReportService {

    @PersistenceContext
    private EntityManager em;

    public Map<String, Object> report(int days) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("window_days", days);
        out.put("episodes", episodeSummary(days));
        out.put("doc_gaps", docGaps(days));
        out.put("plan_edits", planEdits(days));
        out.put("cost_by_agent", costByAgent(days));
        out.put("divergences", divergences(days));
        out.put("repair_outcomes", repairOutcomes(days));
        return out;
    }

    /** Total / finished-rate / avg steps per episode. */
    private Map<String, Object> episodeSummary(int days) {
        Object[] row = (Object[]) em.createNativeQuery("""
                SELECT count(*),
                       count(*) FILTER (WHERE status = 'finished'),
                       count(*) FILTER (WHERE divergence),
                       COALESCE(avg(s.cnt), 0)
                FROM agent_episodes e
                LEFT JOIN (SELECT episode_id, count(*) AS cnt
                           FROM agent_steps GROUP BY episode_id) s
                       ON s.episode_id = e.id
                WHERE e.started_at > now() - make_interval(days => :d)
                """).setParameter("d", days).getSingleResult();
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("total", ((Number) row[0]).longValue());
        m.put("finished", ((Number) row[1]).longValue());
        m.put("divergent", ((Number) row[2]).longValue());
        m.put("avg_steps", Math.round(((Number) row[3]).doubleValue() * 10) / 10.0);
        return m;
    }

    /** Doc-gap Top-N: verifier rejects grouped by block (spec §5 row 1-2). */
    private List<Map<String, Object>> docGaps(int days) {
        List<?> rows = em.createNativeQuery("""
                SELECT (st.payload::jsonb)->>'block_id' AS block,
                       count(*) AS rejects,
                       count(DISTINCT st.episode_id) AS builds
                FROM agent_steps st
                JOIN agent_episodes e ON e.id = st.episode_id
                WHERE st.event_type = 'verifier_reject'
                  AND e.started_at > now() - make_interval(days => :d)
                  AND (st.payload::jsonb)->>'block_id' IS NOT NULL
                GROUP BY 1 ORDER BY 2 DESC LIMIT 10
                """).setParameter("d", days).getResultList();
        return rows(rows, "block", "rejects", "builds");
    }

    /** Recent plan_user_edited payloads (repeated-pattern raw material). */
    private List<Map<String, Object>> planEdits(int days) {
        List<?> rows = em.createNativeQuery("""
                SELECT e.episode_key, left(st.payload, 500), st.ts::text
                FROM agent_steps st
                JOIN agent_episodes e ON e.id = st.episode_id
                WHERE st.event_type = 'plan_user_edited'
                  AND e.started_at > now() - make_interval(days => :d)
                ORDER BY st.ts DESC LIMIT 20
                """).setParameter("d", days).getResultList();
        return rows(rows, "episode_key", "edit_payload", "ts");
    }

    /** Per-agent cost rollup across builds (C6). */
    private List<Map<String, Object>> costByAgent(int days) {
        List<?> rows = em.createNativeQuery("""
                SELECT st.agent,
                       count(*) AS calls,
                       COALESCE(sum(st.input_tokens), 0) AS input,
                       COALESCE(sum(st.output_tokens), 0) AS output,
                       COALESCE(sum(st.cache_read), 0) AS cache_read
                FROM agent_steps st
                JOIN agent_episodes e ON e.id = st.episode_id
                WHERE st.event_type = 'llm_usage'
                  AND e.started_at > now() - make_interval(days => :d)
                GROUP BY 1 ORDER BY 3 DESC
                """).setParameter("d", days).getResultList();
        return rows(rows, "agent", "calls", "input", "output", "cache_read");
    }

    /** Divergent episodes — self-ok but user rejected (the gold list). */
    private List<Map<String, Object>> divergences(int days) {
        List<?> rows = em.createNativeQuery("""
                SELECT episode_key, left(instruction, 120), left(user_feedback, 300)
                FROM agent_episodes
                WHERE divergence
                  AND started_at > now() - make_interval(days => :d)
                ORDER BY id DESC LIMIT 20
                """).setParameter("d", days).getResultList();
        return rows(rows, "episode_key", "instruction", "user_feedback");
    }

    /** repair_outcome result distribution. */
    private List<Map<String, Object>> repairOutcomes(int days) {
        List<?> rows = em.createNativeQuery("""
                SELECT (st.payload::jsonb)->>'result', count(*)
                FROM agent_steps st
                JOIN agent_episodes e ON e.id = st.episode_id
                WHERE st.event_type = 'repair_outcome'
                  AND e.started_at > now() - make_interval(days => :d)
                GROUP BY 1 ORDER BY 2 DESC
                """).setParameter("d", days).getResultList();
        return rows(rows, "result", "count");
    }

    private static List<Map<String, Object>> rows(List<?> raw, String... cols) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Object r : raw) {
            Object[] arr = r instanceof Object[] a ? a : new Object[]{r};
            Map<String, Object> m = new LinkedHashMap<>();
            for (int i = 0; i < cols.length && i < arr.length; i++) {
                m.put(cols[i], arr[i]);
            }
            out.add(m);
        }
        return out;
    }
}
