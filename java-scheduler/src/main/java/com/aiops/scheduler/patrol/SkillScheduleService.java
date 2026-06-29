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

	/** target labels (in trigger_config) for schedule scope. */
	private static final String TARGET_ALL_TOOLS = "所有機台";
	private static final String TARGET_SINGLE_TOOL = "單一機台";

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
		final String tool = cfg.get("tool") != null ? String.valueOf(cfg.get("tool")).trim() : "";

		// Single-tool schedule: dispatch only the chosen machine.
		if (TARGET_SINGLE_TOOL.equals(target) && !tool.isBlank()) {
			lockService.runWithLock("skill_v2:" + id + ":" + tool, Duration.ofMinutes(5), () -> {
				boolean ok = skillApiClient.dispatchSkillV2(id, "system_schedule", Map.of("tool_id", tool));
				if (ok) log.info("SkillScheduleService: fired skill_v2={} tool={}", s.getSlug(), tool);
			});
			return;
		}

		// All-tools fan-out — ONLY when the pipeline actually consumes $tool_id.
		// A pinned/none/mixed pipeline can't be fanned out (injection is ignored),
		// so we fall through to a single run instead of faking N identical runs.
		if (TARGET_ALL_TOOLS.equals(target)) {
			String binding = scanToolBinding(s.getPipelineId());
			if ("PARAMETERIZED".equals(binding)) {
				List<String> tools = listToolIds();
				if (!tools.isEmpty()) {
					log.info("SkillScheduleService: fan-out skill_v2={} over {} tools", s.getSlug(), tools.size());
					for (String t : tools) {
						lockService.runWithLock("skill_v2:" + id + ":" + t, Duration.ofMinutes(5), () -> {
							boolean ok = skillApiClient.dispatchSkillV2(id, "system_schedule", Map.of("tool_id", t));
							if (ok) log.info("SkillScheduleService: fired skill_v2={} tool={}", s.getSlug(), t);
						});
					}
					return;
				}
				log.warn("SkillScheduleService: skill_v2={} targets 所有機台 but tool list empty — single run", s.getSlug());
			} else {
				log.warn("SkillScheduleService: skill_v2={} targets 所有機台 but pipeline binding={} "
						+ "(not parameterized) — single run, NOT faking fan-out", s.getSlug(), binding);
			}
		}

		// Single run (pinned tool_id, tool-agnostic, or fallbacks above).
		lockService.runWithLock("skill_v2:" + id, Duration.ofMinutes(5), () -> {
			boolean ok = skillApiClient.dispatchSkillV2(id, "system_schedule", Map.of());
			if (ok) log.info("SkillScheduleService: fired skill_v2={} ({})", s.getSlug(), role);
		});
	}

	/**
	 * Classify how the pipeline supplies tool_id by scanning data-source node
	 * params (NOT just the input declaration): PARAMETERIZED ($tool_id) /
	 * PINNED (literal) / NONE / MIXED. Mirrors SkillV2Service.deriveToolBinding.
	 */
	private String scanToolBinding(Long pipelineId) {
		if (pipelineId == null) return "NONE";
		var pipe = pipelineRepo.findById(pipelineId).orElse(null);
		if (pipe == null) return "NONE";
		Map<String, Object> pj = parseJson(pipe.getPipelineJson());
		Object nodes = pj.get("nodes");
		if (!(nodes instanceof List<?> list)) return "NONE";
		boolean paramRef = false;
		java.util.Set<String> literals = new java.util.LinkedHashSet<>();
		for (Object n : list) {
			if (!(n instanceof Map<?, ?> node)) continue;
			Object paramsObj = node.get("params");
			if (!(paramsObj instanceof Map<?, ?> params)) continue;
			Object tid = params.get("tool_id");
			if (tid == null) continue;
			String val = String.valueOf(tid).trim();
			if (val.isBlank()) continue;
			if (val.startsWith("$")) paramRef = true;
			else literals.add(val);
		}
		if (!paramRef && literals.isEmpty()) return "NONE";
		if (paramRef && literals.isEmpty()) return "PARAMETERIZED";
		if (!paramRef && literals.size() == 1) return "PINNED";
		return "MIXED";
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
