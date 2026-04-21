package com.aiops.api.domain.skill;

import com.aiops.api.domain.common.Auditable;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "cron_jobs",
		indexes = {
				@Index(name = "ix_cron_jobs_skill_id", columnList = "skill_id"),
				@Index(name = "ix_cron_jobs_status", columnList = "status")
		})
public class CronJobEntity extends Auditable {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "skill_id", nullable = false)
	private Long skillId;

	@Column(name = "schedule", nullable = false, length = 100)
	private String schedule;

	@Column(name = "timezone", nullable = false, length = 50)
	private String timezone = "Asia/Taipei";

	@Column(name = "label", nullable = false, length = 200)
	private String label = "";

	/** active | paused | deleted */
	@Column(name = "status", nullable = false, length = 20)
	private String status = "active";

	@Column(name = "created_by", length = 100)
	private String createdBy;

	@Column(name = "last_run_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime lastRunAt;

	@Column(name = "next_run_at", columnDefinition = "timestamp with time zone")
	private OffsetDateTime nextRunAt;
}
