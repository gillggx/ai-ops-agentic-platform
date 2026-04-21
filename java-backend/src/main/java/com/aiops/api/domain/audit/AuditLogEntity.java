package com.aiops.api.domain.audit;

import com.aiops.api.domain.common.CreatedAtOnly;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "audit_logs",
		indexes = {
				@Index(name = "ix_audit_logs_created_at", columnList = "created_at"),
				@Index(name = "ix_audit_logs_user_id", columnList = "user_id"),
				@Index(name = "ix_audit_logs_endpoint", columnList = "endpoint")
		})
public class AuditLogEntity extends CreatedAtOnly {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "user_id")
	private Long userId;

	@Column(name = "username", length = 150)
	private String username;

	/** Pipe-separated roles e.g. "IT_ADMIN" or "PE|ON_DUTY". */
	@Column(name = "roles", length = 100)
	private String roles;

	@Column(name = "http_method", nullable = false, length = 10)
	private String httpMethod;

	@Column(name = "endpoint", nullable = false, length = 300)
	private String endpoint;

	@Column(name = "status_code")
	private Integer statusCode;

	@Column(name = "duration_ms")
	private Long durationMs;

	@Column(name = "remote_ip", length = 45)
	private String remoteIp;

	@Column(name = "user_agent", length = 500)
	private String userAgent;

	@Column(name = "request_body", columnDefinition = "text")
	private String requestBody;

	@Column(name = "error_message", columnDefinition = "text")
	private String errorMessage;
}
