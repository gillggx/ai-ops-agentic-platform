package com.aiops.api.domain.common;

import jakarta.persistence.Column;
import jakarta.persistence.MappedSuperclass;
import lombok.Getter;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;

import java.time.OffsetDateTime;

/** Superclass for entities that only track creation time (e.g. append-only logs). */
@Getter
@Setter
@MappedSuperclass
public abstract class CreatedAtOnly {

	@CreationTimestamp
	@Column(name = "created_at", nullable = false, columnDefinition = "timestamp with time zone")
	private OffsetDateTime createdAt;
}
