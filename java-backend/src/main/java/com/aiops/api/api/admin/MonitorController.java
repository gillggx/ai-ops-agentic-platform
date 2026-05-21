package com.aiops.api.api.admin;

import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.domain.audit.AuditLogRepository;
import com.aiops.api.domain.event.GeneratedEventRepository;
import com.aiops.api.domain.event.NatsEventLogRepository;
import com.aiops.api.domain.patrol.AutoPatrolRepository;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.skill.ExecutionLogRepository;
import com.aiops.api.domain.skill.SkillDefinitionRepository;
import com.aiops.api.domain.user.UserRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/** Platform dashboard counts for IT_ADMIN. */
@RestController
@RequestMapping("/api/v1/admin/monitor")
@PreAuthorize(Authorities.ADMIN)
public class MonitorController {

	private final UserRepository userRepo;
	private final AlarmRepository alarmRepo;
	private final SkillDefinitionRepository skillRepo;
	private final PipelineRepository pipelineRepo;
	private final AutoPatrolRepository patrolRepo;
	private final ExecutionLogRepository execLogRepo;
	private final GeneratedEventRepository generatedEventRepo;
	private final NatsEventLogRepository natsLogRepo;
	private final AuditLogRepository auditRepo;

	public MonitorController(UserRepository userRepo,
	                         AlarmRepository alarmRepo,
	                         SkillDefinitionRepository skillRepo,
	                         PipelineRepository pipelineRepo,
	                         AutoPatrolRepository patrolRepo,
	                         ExecutionLogRepository execLogRepo,
	                         GeneratedEventRepository generatedEventRepo,
	                         NatsEventLogRepository natsLogRepo,
	                         AuditLogRepository auditRepo) {
		this.userRepo = userRepo;
		this.alarmRepo = alarmRepo;
		this.skillRepo = skillRepo;
		this.pipelineRepo = pipelineRepo;
		this.patrolRepo = patrolRepo;
		this.execLogRepo = execLogRepo;
		this.generatedEventRepo = generatedEventRepo;
		this.natsLogRepo = natsLogRepo;
		this.auditRepo = auditRepo;
	}

	@GetMapping
	public ApiResponse<Map<String, Object>> summary() {
		return ApiResponse.ok(Map.of(
				"users", userRepo.count(),
				"alarms", alarmRepo.count(),
				"skills", skillRepo.count(),
				"pipelines", pipelineRepo.count(),
				"auto_patrols", patrolRepo.count(),
				"execution_logs", execLogRepo.count(),
				"generated_events", generatedEventRepo.count(),
				"nats_event_logs", natsLogRepo.count(),
				"audit_logs", auditRepo.count()
		));
	}
}
