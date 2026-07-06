package com.aiops.api.domain.llm;

import java.io.Serializable;
import java.time.LocalDate;
import java.util.Objects;

/** Composite PK (day, model) for {@link LlmProviderDailyEntity} — JPA
 *  {@code @IdClass}, so: public no-arg ctor + Serializable + equals/hashCode
 *  over both fields. */
public class LlmProviderDailyId implements Serializable {

    private static final long serialVersionUID = 1L;

    private LocalDate day;
    private String model;

    public LlmProviderDailyId() {
    }

    public LlmProviderDailyId(LocalDate day, String model) {
        this.day = day;
        this.model = model;
    }

    public LocalDate getDay() {
        return day;
    }

    public String getModel() {
        return model;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof LlmProviderDailyId other)) return false;
        return Objects.equals(day, other.day) && Objects.equals(model, other.model);
    }

    @Override
    public int hashCode() {
        return Objects.hash(day, model);
    }
}
