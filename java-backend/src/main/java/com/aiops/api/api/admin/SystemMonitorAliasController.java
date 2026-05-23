package com.aiops.api.api.admin;

import com.aiops.api.api.skill.SkillRunnerService;
import com.aiops.api.auth.Authorities;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeRepository;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.domain.audit.AuditLogRepository;
import com.aiops.api.domain.blockdoc.BlockDocRepository;
import com.aiops.api.domain.event.GeneratedEventRepository;
import com.aiops.api.domain.event.NatsEventLogRepository;
import com.aiops.api.domain.mcp.McpDefinitionRepository;
import com.aiops.api.domain.patrol.AutoPatrolRepository;
import com.aiops.api.domain.pipeline.BlockRepository;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.pipeline.PipelineRunRepository;
import com.aiops.api.domain.skill.ExecutionLogRepository;
import com.aiops.api.domain.skill.SkillDefinitionRepository;
import com.aiops.api.domain.skill.SkillRunRepository;
import com.aiops.api.domain.user.UserRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Path-parity alias for Frontend's {@code /system/monitor} page. Returns
 * the bare JSON shape the Next.js page consumes (no envelope wrap):
 *   {timestamp, services, background_tasks, db_stats, build_info}
 *
 * 2026-05-23: complete audit + rewrite.
 *  - dropped legacy fastapi-backend:8001 entry (decommissioned 2026-04-25)
 *  - added aiops-app:8000 + aiops-java-scheduler:8003 (real running units)
 *  - replaced hardcoded "UP" with per-service /health ping (real status)
 *  - dropped fetchPollerStats() — the Python event poller is gone; Java
 *    scheduler now owns event dispatch (see aiops-java-scheduler)
 *  - extended db_stats: agent_knowledge, pb_blocks, block_docs,
 *    mcp_definitions, skill_runs, pb_pipeline_runs
 */
@RestController
@RequestMapping("/api/v1/system/monitor")
@PreAuthorize(Authorities.ANY_ROLE)
public class SystemMonitorAliasController {

	private final UserRepository userRepo;
	private final AlarmRepository alarmRepo;
	private final SkillDefinitionRepository skillRepo;
	private final SkillRunRepository skillRunRepo;
	private final PipelineRepository pipelineRepo;
	private final PipelineRunRepository pipelineRunRepo;
	private final AutoPatrolRepository patrolRepo;
	private final ExecutionLogRepository execLogRepo;
	private final GeneratedEventRepository generatedEventRepo;
	private final NatsEventLogRepository natsLogRepo;
	private final AuditLogRepository auditRepo;
	private final AgentKnowledgeRepository knowledgeRepo;
	private final BlockRepository blockRepo;
	private final BlockDocRepository blockDocRepo;
	private final McpDefinitionRepository mcpRepo;
	private final SkillRunnerService skillRunner;

	/** Cached WebClient — health pings reuse it across requests instead of
	 *  re-instantiating per call (per-call clients leak connection pools). */
	private static final WebClient HEALTH_CLIENT = WebClient.builder().build();
	private static final Duration HEALTH_TIMEOUT = Duration.ofSeconds(2);

	public SystemMonitorAliasController(UserRepository userRepo,
	                                    AlarmRepository alarmRepo,
	                                    SkillDefinitionRepository skillRepo,
	                                    SkillRunRepository skillRunRepo,
	                                    PipelineRepository pipelineRepo,
	                                    PipelineRunRepository pipelineRunRepo,
	                                    AutoPatrolRepository patrolRepo,
	                                    ExecutionLogRepository execLogRepo,
	                                    GeneratedEventRepository generatedEventRepo,
	                                    NatsEventLogRepository natsLogRepo,
	                                    AuditLogRepository auditRepo,
	                                    AgentKnowledgeRepository knowledgeRepo,
	                                    BlockRepository blockRepo,
	                                    BlockDocRepository blockDocRepo,
	                                    McpDefinitionRepository mcpRepo,
	                                    SkillRunnerService skillRunner) {
		this.userRepo = userRepo;
		this.alarmRepo = alarmRepo;
		this.skillRepo = skillRepo;
		this.skillRunRepo = skillRunRepo;
		this.pipelineRepo = pipelineRepo;
		this.pipelineRunRepo = pipelineRunRepo;
		this.patrolRepo = patrolRepo;
		this.execLogRepo = execLogRepo;
		this.generatedEventRepo = generatedEventRepo;
		this.natsLogRepo = natsLogRepo;
		this.auditRepo = auditRepo;
		this.knowledgeRepo = knowledgeRepo;
		this.blockRepo = blockRepo;
		this.blockDocRepo = blockDocRepo;
		this.mcpRepo = mcpRepo;
		this.skillRunner = skillRunner;
	}

	@GetMapping
	public Map<String, Object> monitor() {
		// ── Service health (real ping, not hardcoded) ────────────────────
		// LinkedHashMap so frontend renders in a predictable order.
		Map<String, Object> services = new LinkedHashMap<>();
		services.put("aiops-app",             probe(8000, "/api/health"));
		services.put("aiops-java-api",        probe(8002, "/actuator/health"));
		services.put("aiops-java-scheduler",  probe(8003, "/actuator/health"));
		services.put("aiops-python-sidecar",  probe(8050, "/health"));
		services.put("ontology-simulator",    probe(8012, "/api/v1/tools"));

		// ── Background tasks ─────────────────────────────────────────────
		// event_poller was Python-side and is gone (Java scheduler owns
		// dispatch now); cron_scheduler is also Java now. SkillRunner
		// in-memory counters surface alarm-emit activity.
		Map<String, Object> bg = new HashMap<>();
		Map<String, Object> scheduler = new HashMap<>();
		scheduler.put("status", "JAVA");
		scheduler.put("note", "aiops-java-scheduler unit handles cron + event dispatch");
		bg.put("cron_scheduler", scheduler);
		bg.put("skill_runner", skillRunner.alarmEmitStats());

		// ── DB stats ─────────────────────────────────────────────────────
		Map<String, Object> dbStats = new LinkedHashMap<>();
		// Core domain
		dbStats.put("users", userRepo.count());
		dbStats.put("alarms", alarmRepo.count());
		dbStats.put("audit_logs", auditRepo.count());
		// Skill / pipeline domain
		dbStats.put("skills", skillRepo.count());
		dbStats.put("skill_runs", skillRunRepo.count());
		dbStats.put("pipelines", pipelineRepo.count());
		dbStats.put("pb_pipeline_runs", pipelineRunRepo.count());
		dbStats.put("execution_logs", execLogRepo.count());
		// Block / MCP / Knowledge — the libraries agent reads from
		dbStats.put("pb_blocks", blockRepo.count());
		dbStats.put("block_docs", blockDocRepo.count());
		dbStats.put("mcp_definitions", mcpRepo.count());
		dbStats.put("agent_knowledge", knowledgeRepo.count());
		// Patrol / event infrastructure
		dbStats.put("auto_patrols", patrolRepo.count());
		dbStats.put("generated_events", generatedEventRepo.count());
		dbStats.put("nats_event_logs", natsLogRepo.count());

		Map<String, Object> out = new LinkedHashMap<>();
		out.put("timestamp", Instant.now().toString());
		out.put("services", services);
		out.put("background_tasks", bg);
		out.put("db_stats", dbStats);
		out.put("build_info", Map.of("backend", "java-spring-boot-3.5",
				"service", "aiops-java-api"));
		return out;
	}

	/** Probe a service's health endpoint on localhost. Returns
	 *  {status: "UP"|"DOWN", port, ...} consumed by frontend status badge.
	 *  Any non-2xx, timeout, or connection error → DOWN. */
	private static Map<String, Object> probe(int port, String path) {
		Map<String, Object> out = new HashMap<>();
		out.put("port", port);
		try {
			HEALTH_CLIENT.get()
					.uri("http://127.0.0.1:" + port + path)
					.retrieve()
					.toBodilessEntity()
					.timeout(HEALTH_TIMEOUT)
					.block();
			out.put("status", "UP");
		} catch (Exception ex) {
			out.put("status", "DOWN");
			// Truncate to keep payload small; full trace lives in journalctl
			out.put("error", ex.getClass().getSimpleName() + ": "
					+ String.valueOf(ex.getMessage()).split("\n")[0]);
		}
		return out;
	}
}
