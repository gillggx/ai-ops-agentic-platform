package com.aiops.api.api.admin;

import com.aiops.api.auth.Authorities;
import com.aiops.api.config.AiopsProperties;
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
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
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
	private final AiopsProperties props;
	private final WebClient legacyClient;

	public SystemMonitorAliasController(UserRepository userRepo, AlarmRepository alarmRepo,
	                                    SkillDefinitionRepository skillRepo, PipelineRepository pipelineRepo,
	                                    AutoPatrolRepository patrolRepo, ExecutionLogRepository execLogRepo,
	                                    GeneratedEventRepository generatedEventRepo,
	                                    NatsEventLogRepository natsLogRepo,
	                                    AgentMemoryRepository agentMemoryRepo,
	                                    AuditLogRepository auditRepo,
	                                    AiopsProperties props,
	                                    @Value("${aiops.legacy-backend-url:http://127.0.0.1:8001}") String legacyBackendUrl) {
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
		this.props = props;
		this.legacyClient = WebClient.builder().baseUrl(legacyBackendUrl).build();
	}

	@GetMapping
	public Map<String, Object> monitor() {
		// Frontend compares status to "UP" (uppercase) — keep consistent.
		Map<String, Object> services = new HashMap<>();
		services.put("aiops-java-api", Map.of("status", "UP", "port", 8002));
		services.put("aiops-python-sidecar", Map.of("status", "UP", "port", 8050));
		services.put("fastapi-backend", Map.of("status", "UP", "port", 8001,
				"note", "legacy Python; runs event poller + DR engine"));
		services.put("ontology-simulator", Map.of("status", "UP", "port", 8012));

		// Poller stats — fetch from Python :8001 where the poller actually
		// runs. Fall back to a grey-EXTERNAL stub if Python is unreachable.
		Map<String, Object> poller = fetchPollerStats();

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

	private static final org.slf4j.Logger log =
			org.slf4j.LoggerFactory.getLogger(SystemMonitorAliasController.class);

	/** Fetch poller runtime stats from the legacy Python backend. */
	@SuppressWarnings("unchecked")
	private Map<String, Object> fetchPollerStats() {
		String secret = props.auth() != null ? props.auth().sharedSecretToken() : null;
		Map<String, Object> stub = new HashMap<>();
		stub.put("status", "UNREACHABLE");
		stub.put("started_at", null);
		stub.put("last_poll_at", null);
		stub.put("last_seen_event", null);
		stub.put("total_polls", 0);
		stub.put("total_events_processed", 0);
		stub.put("ooc_detected", 0);
		stub.put("skills_triggered", 0);
		stub.put("errors", 0);

		if (secret == null || secret.isBlank()) {
			log.warn("poller-stats: no shared-secret configured");
			return stub;
		}
		try {
			Map<String, Object> pyResp = legacyClient.get()
					.uri("/api/v1/system/monitor")
					.header("Authorization", "Bearer " + secret)
					.retrieve()
					.bodyToMono(Map.class)
					.timeout(Duration.ofSeconds(3))
					.block();
			if (pyResp == null) {
				log.warn("poller-stats: Python returned null");
				return stub;
			}
			log.debug("poller-stats: pyResp keys={}", pyResp.keySet());
			// Python returns a bare {timestamp, services, background_tasks, db_stats};
			// no {ok, data} envelope here.
			Object tasks = pyResp.get("background_tasks");
			if (!(tasks instanceof Map)) {
				log.warn("poller-stats: no background_tasks in Python response (keys={})", pyResp.keySet());
				return stub;
			}
			Object p = ((Map<String, Object>) tasks).get("event_poller");
			if (p instanceof Map) return (Map<String, Object>) p;
			log.warn("poller-stats: no event_poller in background_tasks");
			return stub;
		} catch (Exception e) {
			log.warn("poller-stats fetch failed: {}", e.toString());
			return stub;
		}
	}
}
