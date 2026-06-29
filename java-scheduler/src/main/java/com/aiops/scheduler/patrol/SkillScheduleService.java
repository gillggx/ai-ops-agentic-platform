package com.aiops.scheduler.patrol;

import com.aiops.api.domain.skill.SkillRunRepository;
import com.aiops.scheduler.lock.DistributedLockService;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * v6.1 (2026-05-20): Phase 11 v6 migration — fire schedule-mode skills.
 *
 * <p>Phase 11 v6 moved trigger config from {@code auto_patrols.cron_expr}
 * to {@code skill_documents.trigger_config} (JSON). java-scheduler's
 * existing {@link AutoPatrolSchedulerService} only watches the legacy
 * patrol table, so {@code status='stable'} skills with schedule triggers
 * never fired automatically. This service closes that gap.
 *
 * <p>Approach: minute-granular poll instead of dynamic Spring TaskScheduler
 * registration. With typical N &lt; 10 stable skills, scanning is cheap;
 * the 60s tick is sufficient for hourly/daily modes. Sub-minute precision
 * is not required for SPC patrols.
 *
 * <p>Supported {@code trigger_config.schedule.mode}:
 * <ul>
 *   <li>{@code hourly} — fire every {@code every} hours (default 1)</li>
 *   <li>{@code daily} — fire every {@code every} days (default 1)</li>
 *   <li>{@code cron} — TODO (parse {@code schedule.cron} via CronExpression)</li>
 * </ul>
 *
 * <p>Dedupe: per-skill 5-min Redis lock, same as the patrol/event paths,
 * so a skill that overlaps cron + event triggers only runs once.
 */
@Slf4j
@Service
public class SkillScheduleService {

	private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

	private final SkillRunRepository runRepo;
	private final SkillApiClient skillApiClient;
	private final DistributedLockService lockService;
	private final ObjectMapper objectMapper;
	private final com.aiops.api.domain.skillv2.SkillV2Repository skillV2Repo;
	private final com.aiops.api.domain.pipeline.PipelineRepository pipelineRepo;
	private final SimulatorClient simulatorClient;

	/** target label (in trigger_config) that means "every tool" → fan out. */
	private static final String TARGET_ALL_TOOLS = "所有機台";

	public SkillScheduleService(SkillRunRepository runRepo,
	                            SkillApiClient skillApiClient,
	                            DistributedLockService lockService,
	                            ObjectMapper objectMapper,
	                            com.aiops.api.domain.skillv2.SkillV2Repository skillV2Repo,
	                            com.aiops.api.domain.pipeline.PipelineRepository pipelineRepo,
	                            SimulatorClient simulatorClient) {
		this.runRepo = runRepo;
		this.skillApiClient = skillApiClient;
		this.lockService = lockService;
		this.objectMapper = objectMapper;
		this.skillV2Repo = skillV2Repo;
		this.pipelineRepo = pipelineRepo;
		this.simulatorClient = simulatorClient;
	}

	/**
	 * Poll once per minute. Cheap when no schedule-mode skills exist; the
	 * lock service blocks duplicate fires across pods.
	 */
	@Scheduled(fixedDelay = 60_000, initialDelay = 30_000)
	public void tick() {
		// Legacy skill_documents schedule scan removed in the legacy-skill
		// sunset (2026-06-29). Only the skills_v2 path remains.
		tickV2();
	}

	/**
	 * skills_v2 cron path. Scans active patrol/datacheck skills with a
	 * schedule-mode trigger, uses the deterministic schedule_spec (NOT the NL
	 * display string) to decide due-ness, and fires via the v2 run endpoint.
	 */
	private void tickV2() {
		List<com.aiops.api.domain.skillv2.SkillV2Entity> active =
				skillV2Repo.findByStatusOrderByNameAsc("active");
		for (com.aiops.api.domain.skillv2.SkillV2Entity s : active) {
			String role = s.getRole();
			if (!"patrol".equals(role) && !"datacheck".equals(role)) continue;
			Map<String, Object> cfg = parseJson(s.getTriggerConfig());
			if (!"schedule".equals(String.valueOf(cfg.get("kind")))) continue;
			if (!isDueV2(s, cfg)) continue;
			dispatchDueSkill(s, cfg, role);
		}
	}

	/**
	 * Fire a due skill. If its pipeline declares a {@code tool_id} input AND the
	 * trigger targets every tool ({@code 所有機台}), fan out one run per tool with
	 * {tool_id: T} so each machine gets its own verdict/alarm. Otherwise a single
	 * run with an empty payload (pipelines with a hardcoded tool_id, or no input).
	 */
	private void dispatchDueSkill(com.aiops.api.domain.skillv2.SkillV2Entity s,
	                              Map<String, Object> cfg, String role) {
		final Long id = s.getId();
		final String target = String.valueOf(cfg.getOrDefault("target", ""));

		if (TARGET_ALL_TOOLS.equals(target) && pipelineDeclaresToolId(s.getPipelineId())) {
			List<String> tools = listToolIds();
			if (tools.isEmpty()) {
				log.warn("SkillScheduleService: skill_v2={} targets 所有機台 but tool list is empty — single run", s.getSlug());
			} else {
				log.info("SkillScheduleService: fan-out skill_v2={} over {} tools", s.getSlug(), tools.size());
				for (String tool : tools) {
					// Per-(skill,tool) lock so one tool's fire doesn't block the rest.
					lockService.runWithLock("skill_v2:" + id + ":" + tool, Duration.ofMinutes(5), () -> {
						boolean ok = skillApiClient.dispatchSkillV2(id, "system_schedule", Map.of("tool_id", tool));
						if (ok) log.info("SkillScheduleService: fired skill_v2={} tool={}", s.getSlug(), tool);
					});
				}
				return;
			}
		}

		// Single run (hardcoded tool_id, no tool_id input, or empty tool list fallback).
		lockService.runWithLock("skill_v2:" + id, Duration.ofMinutes(5), () -> {
			boolean ok = skillApiClient.dispatchSkillV2(id, "system_schedule", Map.of());
			if (ok) log.info("SkillScheduleService: fired skill_v2={} ({})", s.getSlug(), role);
		});
	}

	/** True if the pipeline's JSON declares a pipeline-level input named tool_id. */
	private boolean pipelineDeclaresToolId(Long pipelineId) {
		if (pipelineId == null) return false;
		var pipe = pipelineRepo.findById(pipelineId).orElse(null);
		if (pipe == null) return false;
		Map<String, Object> pj = parseJson(pipe.getPipelineJson());
		Object inputs = pj.get("inputs");
		if (!(inputs instanceof List<?> list)) return false;
		for (Object item : list) {
			if (item instanceof Map<?, ?> m && "tool_id".equals(String.valueOf(m.get("name")))) return true;
		}
		return false;
	}

	/** Tool IDs from the simulator. Empty on failure → caller falls back to a single run. */
	private List<String> listToolIds() {
		List<String> ids = new java.util.ArrayList<>();
		for (Map<String, Object> t : simulatorClient.listAllTools()) {
			Object tid = t.get("tool_id");
			if (tid == null) tid = t.get("toolID");
			if (tid != null && !String.valueOf(tid).isBlank()) ids.add(String.valueOf(tid));
		}
		return ids;
	}

	@SuppressWarnings("unchecked")
	private boolean isDueV2(com.aiops.api.domain.skillv2.SkillV2Entity skill, Map<String, Object> cfg) {
		Object specObj = cfg.get("schedule_spec");
		if (!(specObj instanceof Map)) return false;  // pre-Phase-B row → skip until re-saved
		Map<String, Object> spec = (Map<String, Object>) specObj;
		String mode = String.valueOf(spec.getOrDefault("mode", "hourly"));
		Duration interval = switch (mode) {
			case "minutes" -> Duration.ofMinutes(Math.max(1, parseInt(spec.get("every"), 30)));
			case "hourly"  -> Duration.ofHours(Math.max(1, parseInt(spec.get("every"), 1)));
			case "daily_at" -> Duration.ofDays(1);   // first-iteration: treat as daily interval
			default -> Duration.ZERO;
		};
		if (interval.isZero()) return false;
		Optional<OffsetDateTime> last = runRepo.findLastSystemTriggeredAtV2(skill.getId());
		if (last.isEmpty()) return true;  // never fired → start the clock
		return !OffsetDateTime.now().isBefore(last.get().plus(interval));
	}

	// Legacy isDue(SkillDocumentEntity) + tryFire(SkillDocumentEntity) removed in
	// the 2026-06-29 sunset — only the v2 path (isDueV2 + dispatchSkillV2) remains.

	private Map<String, Object> parseJson(String raw) {
		if (raw == null || raw.isBlank()) return Map.of();
		try {
			return objectMapper.readValue(raw, MAP_TYPE);
		} catch (Exception ex) {
			return Map.of();
		}
	}

	private int parseInt(Object v, int def) {
		if (v instanceof Number n) return n.intValue();
		try { return Integer.parseInt(String.valueOf(v)); }
		catch (Exception e) { return def; }
	}
}
