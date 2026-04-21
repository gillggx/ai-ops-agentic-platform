package com.aiops.api.domain.event;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;

import java.time.OffsetDateTime;

@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "nats_event_logs",
		indexes = @Index(name = "ix_nats_event_logs_event_type_name", columnList = "event_type_name"))
public class NatsEventLogEntity {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "event_type_name", nullable = false, length = 100)
	private String eventTypeName;

	@Column(name = "equipment_id", length = 100)
	private String equipmentId;

	@Column(name = "lot_id", length = 100)
	private String lotId;

	@Column(name = "payload", columnDefinition = "text")
	private String payload;

	@CreationTimestamp
	@Column(name = "received_at", nullable = false, columnDefinition = "timestamp with time zone")
	private OffsetDateTime receivedAt;
}
