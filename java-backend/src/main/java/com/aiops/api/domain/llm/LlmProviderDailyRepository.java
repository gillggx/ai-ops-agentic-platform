package com.aiops.api.domain.llm;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDate;
import java.util.List;

public interface LlmProviderDailyRepository
        extends JpaRepository<LlmProviderDailyEntity, LlmProviderDailyId> {

    /** Atomic upsert-increment of today's (day, model) row. Native UPSERT so
     *  concurrent sidecar calls can't lose updates (JPA read-modify-write
     *  would race). {@code empty}/{@code error} are 0/1 flags folded into
     *  the counters via EXCLUDED. */
    @Modifying
    @Query(value = """
            INSERT INTO llm_provider_daily
              (day, model, calls, empty_calls, error_calls,
               input_tokens, output_tokens, cache_read, updated_at)
            VALUES (CURRENT_DATE, :model, 1, :empty, :error,
                    :inputTokens, :outputTokens, :cacheRead, now())
            ON CONFLICT (day, model) DO UPDATE SET
              calls         = llm_provider_daily.calls + 1,
              empty_calls   = llm_provider_daily.empty_calls + EXCLUDED.empty_calls,
              error_calls   = llm_provider_daily.error_calls + EXCLUDED.error_calls,
              input_tokens  = llm_provider_daily.input_tokens + EXCLUDED.input_tokens,
              output_tokens = llm_provider_daily.output_tokens + EXCLUDED.output_tokens,
              cache_read    = llm_provider_daily.cache_read + EXCLUDED.cache_read,
              updated_at    = now()
            """, nativeQuery = true)
    int incrementToday(@Param("model") String model,
                       @Param("empty") int empty,
                       @Param("error") int error,
                       @Param("inputTokens") long inputTokens,
                       @Param("outputTokens") long outputTokens,
                       @Param("cacheRead") long cacheRead);

    List<LlmProviderDailyEntity> findByDayGreaterThanEqualOrderByDayDescModelAsc(LocalDate since);
}
