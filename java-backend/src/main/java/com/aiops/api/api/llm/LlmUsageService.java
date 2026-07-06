package com.aiops.api.api.llm;

import com.aiops.api.common.ApiException;
import com.aiops.api.domain.llm.LlmProviderDailyEntity;
import com.aiops.api.domain.llm.LlmProviderDailyRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * S3 (V75): LLM provider quality rollup — write path is an atomic native
 * UPSERT per call (sidecar fires one increment per LLM response), read path
 * is the Supervisor's /metrics/llm-daily table.
 */
@Service
public class LlmUsageService {

    /** Guard the read window — the table has one row per (day, model), so
     *  90 days is already generous for a quality dashboard. */
    private static final int MAX_WINDOW_DAYS = 90;
    private static final int MODEL_MAX_LEN = 80;

    private final LlmProviderDailyRepository repo;

    public LlmUsageService(LlmProviderDailyRepository repo) {
        this.repo = repo;
    }

    @Transactional
    public Map<String, Object> increment(String model, boolean empty, boolean error,
                                         long inputTokens, long outputTokens, long cacheRead) {
        if (model == null || model.isBlank()) {
            throw ApiException.badRequest("model required");
        }
        String m = model.length() > MODEL_MAX_LEN ? model.substring(0, MODEL_MAX_LEN) : model;
        int affected = repo.incrementToday(m, empty ? 1 : 0, error ? 1 : 0,
                Math.max(0, inputTokens), Math.max(0, outputTokens), Math.max(0, cacheRead));
        return Map.of("updated", affected > 0);
    }

    /** Last {@code days} days (bounded 1..90), newest day first; keys are
     *  snake_case for the wire. */
    @Transactional(readOnly = true)
    public List<Map<String, Object>> daily(int days) {
        int window = Math.min(Math.max(days, 1), MAX_WINDOW_DAYS);
        LocalDate since = LocalDate.now().minusDays(window - 1L);
        List<Map<String, Object>> out = new ArrayList<>();
        for (LlmProviderDailyEntity e : repo.findByDayGreaterThanEqualOrderByDayDescModelAsc(since)) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("day", e.getDay() == null ? null : e.getDay().toString());
            m.put("model", e.getModel());
            m.put("calls", e.getCalls());
            m.put("empty_calls", e.getEmptyCalls());
            m.put("error_calls", e.getErrorCalls());
            m.put("input_tokens", e.getInputTokens());
            m.put("output_tokens", e.getOutputTokens());
            m.put("cache_read", e.getCacheRead());
            m.put("updated_at", e.getUpdatedAt() == null ? null : e.getUpdatedAt().toString());
            out.add(m);
        }
        return out;
    }
}
