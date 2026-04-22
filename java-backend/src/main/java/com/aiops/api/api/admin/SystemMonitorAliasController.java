package com.aiops.api.api.admin;

import com.aiops.api.auth.Authorities;
import com.aiops.api.domain.agent.AgentMemoryRepository;
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

import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Path-parity alias for Frontend's {@code /system/monitor} page. The page
 * consumes the JSON directly (no envelope unwrap), so we return a bare
 * object with the exact shape the Next.js page expects:
 *   { timestamp, services, background_tasks: {event_poller, cron_scheduler},
 *     db_stats }
 */
@RestController
@RequestMapping("/api/v1/system/monitor")
@PreAuthorize(Authorities.ANY_ROLE)
public class SystemMonitorAliasController {

	private final UserRepository userRepo;
	private final AlarmRepository alarmRepo;
	private final SkillDefinitionRepository skillRepo;
	private final PipelineRepository pipelineRepo;
	private final AutoPatrolRepository patrolRepo;
	private final ExecutionLogRepository execLogRepo;
	private final GeneratedEventRepository generatedEventRepo;
	private final NatsEventLogRepository natsLogRepo;
	private final AgentMemoryRepository agentMemoryRepo;
	private final AuditLogRepository auditRepo;

	public SystemMonitorAliasController(UserRepository userRepo, AlarmRepository alarmRepo,
	                                    SkillDefinitionRepository skillRepo, PipelineRepository pipelineRepo,
	                                    AutoPatrolRepository patrolRepo, ExecutionLogRepository execLogRepo,
	                                    GeneratedEventRepository generatedEventRepo,
	                                    NatsEventLogRepository natsLogRepo,
	                                    AgentMemoryRepository agentMemoryRepo,
	                                    AuditLogRepository auditRepo) {
		this.userRepo = userRepo;
		this.alarmRepo = alarmRepo;
		this.skillRepo = skillRepo;
		this.pipelineRepo = pipelineRepo;
		this.patrolRepo = patrolRepo;
		this.execLogRepo = execLogRepo;
		this.generatedEventRepo = generatedEventRepo;
		this.natsLogRepo = natsLogRepo;
		this.agentMemoryRepo = agentMemoryRepo;
		this.auditRepo = auditRepo;
	}

	@GetMapping
	public Map<String, Object> monitor() {
		Map<String, Object> services = new HashMap<>();
		services.put("aiops-java-api", Map.of("status", "up", "port", 8002));
		services.put("aiops-python-sidecar", Map.of("status", "up", "port", 8050));
		services.put("fastapi-backend", Map.of("status", "external", "port", 8001,
				"note", "legacy Python; runs event poller + DR engine"));
		services.put("ontology-simulator", Map.of("status", "external", "port", 8012));

		// Poller stats — owned by the old Python stack, so we report EXTERNAL
		// and don't fabricate numbers. The "last_seen_event" etc. would need
		// to be read out of Python; non-blocking for now.
		Map<String, Object> poller = new HashMap<>();
		poller.put("status", "EXTERNAL");
		poller.put("started_at", null);
		poller.put("last_poll_at", null);
		poller.put("last_seen_event", null);
		poller.put("total_polls", 0);
		poller.put("total_events_processed", 0);
		poller.put("ooc_detected", 0);
		poller.put("skills_triggered", 0);
		poller.put("errors", 0);

		Map<String, Object> scheduler = new HashMap<>();
		scheduler.put("status", "JAVA");
		scheduler.put("jobs", List.of());

		Map<String, Object> dbStats = new HashMap<>();
		dbStats.put("users", userRepo.count());
		dbStats.put("alarms", alarmRepo.count());
		dbStats.put("skills", skillRepo.count());
		dbStats.put("pipelines", pipelineRepo.count());
		dbStats.put("auto_patrols", patrolRepo.count());
		dbStats.put("execution_logs", execLogRepo.count());
		dbStats.put("generated_events", generatedEventRepo.count());
		dbStats.put("nats_event_logs", natsLogRepo.count());
		dbStats.put("agent_memories", agentMemoryRepo.count());
		dbStats.put("audit_logs", auditRepo.count());

		Map<String, Object> out = new HashMap<>();
		out.put("timestamp", Instant.now().toString());
		out.put("services", services);
		out.put("background_tasks", Map.of(
				"event_poller", poller,
				"cron_scheduler", scheduler));
		out.put("db_stats", dbStats);
		out.put("build_info", Map.of("backend", "java-spring-boot-3.5",
				"service", "aiops-java-api"));
		return out;
	}
}
