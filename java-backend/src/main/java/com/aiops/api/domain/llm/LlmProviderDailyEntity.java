package com.aiops.api.domain.llm;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * S3 (V75): per-day per-model LLM provider quality rollup — call counts,
 * empty-response / error rates, token volume. Rows are written exclusively
 * through {@link LlmProviderDailyRepository#incrementToday} (native UPSERT);
 * JPA save() is never used for increments (read-modify-write would race
 * under concurrent sidecar calls).
 */
@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "llm_provider_daily")
@IdClass(LlmProviderDailyId.class)
public class LlmProviderDailyEntity {

    @Id
    @Column(name = "day", nullable = false)
    private LocalDate day;

    @Id
    @Column(name = "model", nullable = false, length = 80)
    private String model;

    @Column(name = "calls", nullable = false)
    private Integer calls = 0;

    /** finish=stop but content entirely empty. */
    @Column(name = "empty_calls", nullable = false)
    private Integer emptyCalls = 0;

    /** finish_reason='error' / exception. */
    @Column(name = "error_calls", nullable = false)
    private Integer errorCalls = 0;

    @Column(name = "input_tokens", nullable = false)
    private Long inputTokens = 0L;

    @Column(name = "output_tokens", nullable = false)
    private Long outputTokens = 0L;

    @Column(name = "cache_read", nullable = false)
    private Long cacheRead = 0L;

    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt = OffsetDateTime.now();
}
