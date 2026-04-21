package com.aiops.api.domain.common;

import jakarta.persistence.Column;
import jakarta.persistence.MappedSuperclass;
import lombok.Getter;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.OffsetDateTime;

@Getter
@Setter
@MappedSuperclass
public abstract class Auditable {

	@CreationTimestamp
	@Column(name = "created_at", nullable = false, columnDefinition = "timestamp with time zone")
	private OffsetDateTime createdAt;

	@UpdateTimestamp
	@Column(name = "updated_at", nullable = false, columnDefinition = "timestamp with time zone")
	private OffsetDateTime updatedAt;
}
