package com.aiops.api.api.fleet;

import com.aiops.api.config.AiopsProperties;
import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Backend for the redesigned Dashboard fleet overview (Phase 1).
 *
 * <p>Pulls the equipment roster from the ontology simulator, enriches each
 * row with alarm-derived metrics (OOC count, FDC, hourly bucket, trend,
 * note), and exposes a small rule engine that emits the Top-3 AI concerns.
 *
 * <p>Reads-only — no DB writes. The simulator call is async-blocking via
 * a per-request WebClient (60s budget); alarms come from
 * {@link AlarmRepository#findByEventTimeAfterOrderByEventTimeDesc}.
 *
 * @see <code>docs/SPEC_dashboard_redesign_v1_phase1.md</code>
 */
@Service
public class FleetService {

	private static final Logger log = LoggerFactory.getLogger(FleetService.class);

	private static final int SPARK_BUCKETS = 24;
	/** Score thresholds matching SPEC §2.1. */
	private static final int HEALTHY_THRESHOLD = 80;
	private static final int WARN_THRESHOLD = 50;

	private final AlarmRepository alarmRepo;
	private final WebClient simulatorClient;
	private final ObjectMapper mapper;

	public FleetService(AlarmRepository alarmRepo,
	                    AiopsProperties props,
	                    ObjectMapper mapper) {
		this.alarmRepo = alarmRepo;
		this.mapper = mapper;
		String simBase = props.simulator() != null && props.simulator().baseUrl() != null
				? props.simulator().baseUrl() : "http://localhost:8012";
		this.simulatorClient = WebClient.builder()
				.baseUrl(simBase)
				.codecs(c -> c.defaultCodecs().maxInMemorySize(8 * 1024 * 1024))
				.build();
	}

	// ── Public API ──────────────────────────────────────────────────────────

	public FleetDtos.EquipmentListResponse listEquipment(int sinceHours) {
		OffsetDateTime now = OffsetDateTime.now(ZoneOffset.UTC);
		OffsetDateTime since = now.minusHours(Math.max(sinceHours, 1));

		List<Map<String, Object>> tools = fetchToolsFromSimulator();
		List<AlarmEntity> alarms = alarmRepo.findByEventTimeAfterOrderByEventTimeDesc(since);
		Map<String, Map<String, Object>> simSummaryByTool = fetchSimSummaryByTool();

		// Group alarms by equipment for fast per-tool aggregation.
		Map<String, List<AlarmEntity>> alarmsByEq = new HashMap<>();
		for (AlarmEntity a : alarms) {
			if (a.getEquipmentId() == null || a.getEquipmentId().isBlank()) continue;
			alarmsByEq.computeIfAbsent(a.getEquipmentId(), k -> new ArrayList<>()).add(a);
		}

		List<FleetDtos.Equipment> rows = new ArrayList<>();
		for (Map<String, Object> tool : tools) {
			String id = String.valueOf(tool.getOrDefault("tool_id", tool.get("id")));
			String name = String.valueOf(tool.getOrDefault("name", id));
			List<AlarmEntity> own = alarmsByEq.getOrDefault(id, List.of());
			Map<String, Object> simRow = simSummaryByTool.getOrDefault(id, Map.of());
			rows.add(buildEquipment(id, name, own, simRow, since, now));
		}

		// Sort: crit → warn → healthy, tie-break by ooc desc.
		rows.sort(Comparator.<FleetDtos.Equipment>comparingInt(e -> healthRank(e.health()))
				.thenComparingDouble(e -> -e.ooc()));

		return new FleetDtos.EquipmentListResponse(sinceHours + "h", now, rows.size(), rows);
	}

	public FleetDtos.ConcernListResponse computeConcerns(int sinceHours) {
		FleetDtos.EquipmentListResponse list = listEquipment(sinceHours);
		List<FleetDtos.Concern> concerns = new ArrayList<>();
		concerns.addAll(rule1CriticalTool(list.equipment()));
		concerns.addAll(rule2RisingTrend(list.equipment()));
		concerns.addAll(rule3CrossStep(list.equipment(), sinceHours));

		// Sort: crit > warn, then confidence desc.
		concerns.sort(Comparator
				.<FleetDtos.Concern>comparingInt(c -> "crit".equals(c.severity()) ? 0 : 1)
				.thenComparingDouble(c -> -c.confidence()));

		// Cap at 3 (per SPEC §2.1.B).
		if (concerns.size() > 3) concerns = concerns.subList(0, 3);
		return new FleetDtos.ConcernListResponse(
				sinceHours + "h", OffsetDateTime.now(ZoneOffset.UTC), concerns);
	}

	public FleetDtos.FleetStats computeStats(int sinceHours) {
		FleetDtos.EquipmentListResponse list = listEquipment(sinceHours);
		int oocEvents = 0, fdcAlerts = 0, openAlarms = 0, critCount = 0, warnCount = 0;
		Set<String> affectedLots = new HashSet<>();
		double oocSum = 0;
		int oocSamples = 0;

		OffsetDateTime now = OffsetDateTime.now(ZoneOffset.UTC);
		OffsetDateTime since = now.minusHours(Math.max(sinceHours, 1));
		List<AlarmEntity> alarms = alarmRepo.findByEventTimeAfterOrderByEventTimeDesc(since);
		for (AlarmEntity a : alarms) {
			if ("active".equalsIgnoreCase(a.getStatus())) openAlarms++;
			if (a.getLotId() != null && !a.getLotId().isBlank()) affectedLots.add(a.getLotId());
		}

		for (FleetDtos.Equipment e : list.equipment()) {
			oocEvents += e.oocCount();
			fdcAlerts += e.fdc();
			if ("crit".equals(e.health())) critCount++;
			else if ("warn".equals(e.health())) warnCount++;
			if (e.ooc() > 0) {
				oocSum += e.ooc();
				oocSamples++;
			}
		}
		double fleetOocRate = oocSamples > 0 ? oocSum / oocSamples : 0;

		// total_events from simulator's fab-wide summary (one extra HTTP
		// hit; cheap relative to the full fleet enrich). Affected_lots
		// stays alarm-derived for v1; patrol-fired alarms rarely carry a
		// specific lot_id so this often shows 0.
		int totalEvents = fetchSimTotalEvents();

		return new FleetDtos.FleetStats(
				roundOne(fleetOocRate), oocEvents, totalEvents, fdcAlerts,
				openAlarms, affectedLots.size(), critCount, warnCount, now);
	}

	private int fetchSimTotalEvents() {
		try {
			JsonNode root = simulatorClient.get()
					.uri(uri -> uri.path("/api/v1/process/summary").queryParam("since", "24h").build())
					.retrieve()
					.bodyToMono(JsonNode.class)
					.block(Duration.ofSeconds(5));
			if (root == null) return 0;
			return root.path("total_events").asInt(0);
		} catch (Exception ex) {
			log.warn("simulator total_events fetch failed: {}", ex.toString());
			return 0;
		}
	}

	// ── Equipment row builder ──────────────────────────────────────────────

	private FleetDtos.Equipment buildEquipment(String id, String name,
	                                           List<AlarmEntity> alarms,
	                                           Map<String, Object> simRow,
	                                           OffsetDateTime since,
	                                           OffsetDateTime now) {
		int alarmOocCount = 0, fdc = 0, openAlarms = 0;
		String latestAlarmTitle = null;
		OffsetDateTime latestAlarmAt = null;
		for (AlarmEntity a : alarms) {
			String trig = a.getTriggerEvent() == null ? "" : a.getTriggerEvent().toLowerCase();
			if (trig.contains("ooc") || trig.contains("spc")) alarmOocCount++;
			if (trig.contains("fdc")) fdc++;
			if ("active".equalsIgnoreCase(a.getStatus())) openAlarms++;
			OffsetDateTime t = a.getEventTime() != null ? a.getEventTime() : a.getCreatedAt();
			if (t != null && (latestAlarmAt == null || t.isAfter(latestAlarmAt))
					&& "active".equalsIgnoreCase(a.getStatus())) {
				latestAlarmAt = t;
				latestAlarmTitle = a.getTitle();
			}
		}

		// Source priority: simulator's by_tool aggregation (every SPC event,
		// not just the ones that triggered a patrol alarm) → fallback to
		// alarm-derived count when simulator is empty / unreachable.
		int simOocCount = parseInt(simRow.get("ooc_count"));
		int simEventCount = parseInt(simRow.get("count"));
		int oocCount = simOocCount > 0 ? simOocCount : alarmOocCount;
		// lots24h reuses simulator event count as a proxy (simulator has no
		// per-lot count today). Distinct lot_id from alarms is the fallback.
		int lots24h = simEventCount;
		if (lots24h == 0) {
			Set<String> lots = new HashSet<>();
			for (AlarmEntity a : alarms) {
				if (a.getLotId() != null && !a.getLotId().isBlank()) lots.add(a.getLotId());
			}
			lots24h = lots.size();
		}
		double oocPct = lots24h > 0 ? (double) oocCount / lots24h * 100 : 0;

		// hourly[24] — OOC alarm count per hour bucket, oldest → newest.
		// Caveat: only counts alarms that fired (e.g. patrol ≥3 OOC rule),
		// so visualisation under-reports vs the simulator's raw OOC density.
		List<Integer> hourly = bucketHourly(alarms, since, now);

		// score = 100 − (oocPct·2 + capped_alarms·3 + capped_fdc·2), clamped.
		// alarms is capped at 10 because patrol can fire dozens per tool in
		// 24h and the contribution would otherwise dominate; the rate-based
		// oocPct term already captures sustained pressure. Tuned for ~10-30%
		// OOC range.
		int cappedAlarms = Math.min(openAlarms, 10);
		int cappedFdc = Math.min(fdc, 5);
		int penalty = (int) Math.round(oocPct * 2 + cappedAlarms * 3.0 + cappedFdc * 2.0);
		int score = 100 - penalty;
		if (score < 0) score = 0;
		if (score > 100) score = 100;
		String health = score >= HEALTHY_THRESHOLD ? "healthy"
				: score >= WARN_THRESHOLD ? "warn" : "crit";

		String trend = computeTrend(hourly);
		String note = latestAlarmTitle != null ? latestAlarmTitle : "";

		return new FleetDtos.Equipment(
				id, name, health, score, roundOne(oocPct), oocCount, openAlarms,
				fdc, lots24h, trend, note, hourly);
	}

	private List<Integer> bucketHourly(List<AlarmEntity> alarms,
	                                   OffsetDateTime since, OffsetDateTime now) {
		// Count every alarm row into the hour bucket — in v1 every alarm
		// surfaced by the patrol pipeline is an OOC-derived signal, so the
		// trigger_event column ('auto_patrol:N') doesn't carry the
		// 'ooc'/'spc' literal we used to gate on; gating on it nulled the
		// strip. Relax the filter; mis-counting a non-OOC patrol alarm in
		// the strip is a much smaller sin than rendering all-zero rows.
		long winMs = Math.max(Duration.between(since, now).toMillis(), 1);
		int[] buckets = new int[SPARK_BUCKETS];
		for (AlarmEntity a : alarms) {
			OffsetDateTime t = a.getEventTime() != null ? a.getEventTime() : a.getCreatedAt();
			if (t == null) continue;
			long offset = Duration.between(since, t).toMillis();
			int idx = (int) Math.min(SPARK_BUCKETS - 1, Math.max(0, offset * SPARK_BUCKETS / winMs));
			buckets[idx]++;
		}
		List<Integer> out = new ArrayList<>(SPARK_BUCKETS);
		for (int v : buckets) out.add(v);
		return out;
	}

	private String computeTrend(List<Integer> hourly) {
		if (hourly == null || hourly.size() < 16) return "flat";
		double early = 0, late = 0;
		for (int i = 0; i < 8; i++) early += hourly.get(i);
		for (int i = hourly.size() - 8; i < hourly.size(); i++) late += hourly.get(i);
		early /= 8;
		late /= 8;
		if (early == 0 && late == 0) return "flat";
		if (late > early * 1.2 + 0.1) return "down";   // worse
		if (late < early * 0.8 - 0.1) return "up";     // recovering
		return "flat";
	}

	private static int healthRank(String health) {
		return switch (health) {
			case "crit" -> 0;
			case "warn" -> 1;
			case "healthy" -> 2;
			default -> 3;
		};
	}

	// ── Rules ──────────────────────────────────────────────────────────────

	private List<FleetDtos.Concern> rule1CriticalTool(List<FleetDtos.Equipment> eqs) {
		List<FleetDtos.Concern> out = new ArrayList<>();
		int idx = 1;
		for (FleetDtos.Equipment e : eqs) {
			if (!"crit".equals(e.health())) continue;
			String title = String.format("%s 健康度 %d/100，需要立即介入", e.id(), e.score());
			String detail = e.note() != null && !e.note().isBlank()
					? String.format("最近事件：「%s」（24h 累計 %d 件 OOC、%d 件 alarm）",
							e.note(), e.oocCount(), e.alarms())
					: String.format("24h 累計 %d 件 OOC、%d 件 alarm，OOC 率 %.1f%%",
							e.oocCount(), e.alarms(), e.ooc());
			out.add(new FleetDtos.Concern(
					"r1-" + e.id(), "R1_critical_tool", "crit", 1.0,
					title, detail,
					List.of(e.id()), List.of(),
					e.oocCount() + e.alarms(),
					List.of("檢視 " + e.id() + " 詳情", "派工現場工程師", "暫緩高優先 LOT")));
			idx++;
			if (idx > 5) break; // soft cap before final 3-cap in caller
		}
		return out;
	}

	private List<FleetDtos.Concern> rule2RisingTrend(List<FleetDtos.Equipment> eqs) {
		List<FleetDtos.Concern> out = new ArrayList<>();
		for (FleetDtos.Equipment e : eqs) {
			if (!"warn".equals(e.health())) continue;
			if (!"down".equals(e.trend())) continue;
			double recent = recentAvg(e.hourly(), 8);
			if (recent < 1) continue;     // need ≥1 OOC/h late window
			String title = String.format("%s 過去 8 小時 OOC 趨勢上升", e.id());
			String detail = String.format("最近 8h 平均 %.1f 件/h，前段 %.1f 件/h；OOC 率 %.1f%%。建議在惡化前介入。",
					recent, recentAvg(e.hourly().subList(0, 8), 8), e.ooc());
			out.add(new FleetDtos.Concern(
					"r2-" + e.id(), "R2_rising_trend", "warn", 0.85,
					title, detail,
					List.of(e.id()), List.of(),
					e.oocCount(),
					List.of("加入 watchlist", "比對歷史相似模式", "通知 PE 評估")));
		}
		return out;
	}

	private List<FleetDtos.Concern> rule3CrossStep(List<FleetDtos.Equipment> eqs, int sinceHours) {
		// Re-pull alarms to get step distribution (already cached in Hibernate L1 in
		// practice; cheap relative to LLM/SSE).
		OffsetDateTime since = OffsetDateTime.now(ZoneOffset.UTC).minusHours(Math.max(sinceHours, 1));
		Map<String, Set<String>> toolsByStep = new LinkedHashMap<>();
		Map<String, Integer> alarmsByStep = new HashMap<>();
		for (AlarmEntity a : alarmRepo.findByEventTimeAfterOrderByEventTimeDesc(since)) {
			String step = a.getStep();
			if (step == null || step.isBlank()) continue;
			String trig = a.getTriggerEvent() == null ? "" : a.getTriggerEvent().toLowerCase();
			if (!(trig.contains("ooc") || trig.contains("spc"))) continue;
			toolsByStep.computeIfAbsent(step, k -> new HashSet<>()).add(a.getEquipmentId());
			alarmsByStep.merge(step, 1, Integer::sum);
		}
		List<FleetDtos.Concern> out = new ArrayList<>();
		for (Map.Entry<String, Set<String>> entry : toolsByStep.entrySet()) {
			String step = entry.getKey();
			Set<String> toolsHit = entry.getValue();
			if (toolsHit.size() < 2) continue;
			int evidence = alarmsByStep.getOrDefault(step, 0);
			String title = String.format("Step %s 在 %d 台機台同時出現 OOC 群聚", step, toolsHit.size());
			String detail = String.format("%s 各跑出 OOC，24h 累計 %d 起，建議檢查共用 chamber/recipe。",
					String.join("、", toolsHit), evidence);
			out.add(new FleetDtos.Concern(
					"r3-" + step, "R3_cross_step_cluster", "warn", 0.7,
					title, detail,
					new ArrayList<>(toolsHit), List.of(step), evidence,
					List.of("檢視 " + step + " recipe 共用版本", "比對 chamber group 是否相同", "提報 PE")));
		}
		return out;
	}

	// ── Helpers ────────────────────────────────────────────────────────────

	private List<Map<String, Object>> fetchToolsFromSimulator() {
		// Simulator exposes /api/v1/tools returning a flat array of
		// {tool_id, status}. We normalise to {tool_id, name, status} so
		// buildEquipment can read either form.
		try {
			JsonNode root = simulatorClient.get()
					.uri("/api/v1/tools")
					.retrieve()
					.bodyToMono(JsonNode.class)
					.block(Duration.ofSeconds(8));
			if (root == null) return List.of();
			JsonNode items = root.has("items") ? root.get("items") : root;
			if (items == null || !items.isArray()) return List.of();
			TypeReference<List<Map<String, Object>>> typeRef = new TypeReference<>() {};
			return mapper.convertValue(items, typeRef);
		} catch (Exception ex) {
			log.warn("simulator tools fetch failed: {}", ex.toString());
			return List.of();
		}
	}

	@SuppressWarnings("unchecked")
	private Map<String, Map<String, Object>> fetchSimSummaryByTool() {
		try {
			JsonNode root = simulatorClient.get()
					.uri(uri -> uri.path("/api/v1/process/summary").queryParam("since", "24h").build())
					.retrieve()
					.bodyToMono(JsonNode.class)
					.block(Duration.ofSeconds(8));
			if (root == null) return Map.of();
			JsonNode arr = root.get("by_tool");
			if (arr == null || !arr.isArray()) return Map.of();
			Map<String, Map<String, Object>> out = new HashMap<>();
			for (JsonNode row : arr) {
				String id = row.path("toolID").asText(null);
				if (id == null) continue;
				Map<String, Object> m = mapper.convertValue(row, Map.class);
				out.put(id, m);
			}
			return out;
		} catch (Exception ex) {
			log.warn("simulator summary fetch failed: {}", ex.toString());
			return Map.of();
		}
	}

	private static int parseInt(Object v) {
		if (v == null) return 0;
		if (v instanceof Number n) return n.intValue();
		try { return Integer.parseInt(String.valueOf(v)); } catch (NumberFormatException ignored) { return 0; }
	}

	private static double recentAvg(List<Integer> values, int n) {
		if (values == null || values.isEmpty()) return 0;
		int from = Math.max(0, values.size() - n);
		double sum = 0;
		for (int i = from; i < values.size(); i++) sum += values.get(i);
		return sum / Math.max(1, values.size() - from);
	}

	private static double roundOne(double v) {
		return Math.round(v * 10.0) / 10.0;
	}

	// ── Phase 2: per-equipment detail ────────────────────────────────────

	public FleetDtos.TimelineResponse computeTimeline(String equipmentId, int sinceHours) {
		OffsetDateTime now = OffsetDateTime.now(ZoneOffset.UTC);
		OffsetDateTime since = now.minusHours(Math.max(sinceHours, 1));

		List<FleetDtos.TimelineEvent> events = new ArrayList<>();

		// Lane: ooc / apc / fdc / ec — derived from alarms (active or recent
		// active for this equipment within window).
		for (AlarmEntity a : alarmRepo.findByEquipmentIdAndStatus(equipmentId, "active")) {
			OffsetDateTime t = a.getEventTime() != null ? a.getEventTime() : a.getCreatedAt();
			if (t == null || t.isBefore(since)) continue;
			String trig = a.getTriggerEvent() == null ? "" : a.getTriggerEvent().toLowerCase();
			String lane;
			if (trig.contains("ooc") || trig.contains("spc")) lane = "ooc";
			else if (trig.contains("apc")) lane = "apc";
			else if (trig.contains("fdc")) lane = "fdc";
			else if (trig.contains("ec") || trig.contains("temp")) lane = "ec";
			else lane = "ooc"; // default — unrecognised patrol still surfaces
			String sev = severityToLane(a.getSeverity());
			events.add(new FleetDtos.TimelineEvent(t, lane, sev,
					a.getTitle() != null ? a.getTitle() : ("alarm #" + a.getId()),
					a.getStep() != null ? "STEP " + a.getStep() : ""));
		}

		// Lane: lot — distinct LOT IDs from process_history (one event per LOT
		// at first sighting). Hits the simulator with a tool filter.
		List<Map<String, Object>> events500 = fetchProcessEvents(equipmentId, 500);
		Set<String> seenLots = new java.util.LinkedHashSet<>();
		String lastRecipeVer = null;
		for (Map<String, Object> ev : events500) {
			OffsetDateTime t = parseInstant(ev.get("eventTime"));
			if (t == null || t.isBefore(since)) continue;
			String lot = String.valueOf(ev.getOrDefault("lotID", ""));
			if (!lot.isBlank() && !seenLots.contains(lot)) {
				seenLots.add(lot);
				String spcStatus = String.valueOf(ev.getOrDefault("spc_status", "PASS"));
				String sev = "OOC".equalsIgnoreCase(spcStatus) ? "crit" : "ok";
				events.add(new FleetDtos.TimelineEvent(t, "lot", sev,
						lot, "STEP " + ev.getOrDefault("step", "?")));
			}
			// Lane: recipe — emit one event per version transition.
			Map<?, ?> recipe = ev.get("RECIPE") instanceof Map<?, ?> r ? r : null;
			String ver = recipe != null && recipe.get("recipe_version") != null
					? String.valueOf(recipe.get("recipe_version")) : null;
			if (ver != null && lastRecipeVer != null && !ver.equals(lastRecipeVer)) {
				events.add(new FleetDtos.TimelineEvent(t, "recipe", "info",
						"v" + lastRecipeVer + " → v" + ver, ""));
			}
			if (ver != null) lastRecipeVer = ver;
		}

		// Sort newest → oldest for transport stability.
		events.sort(Comparator.comparing(
				FleetDtos.TimelineEvent::t,
				Comparator.nullsLast(Comparator.reverseOrder())));

		return new FleetDtos.TimelineResponse(equipmentId, since, now, events);
	}

	public FleetDtos.ModulesResponse computeModules(String equipmentId, int sinceHours) {
		OffsetDateTime now = OffsetDateTime.now(ZoneOffset.UTC);
		OffsetDateTime since = now.minusHours(Math.max(sinceHours, 1));

		// SPC: count OOC alarms (or simulator OOC events).
		int oocAlarms = 0;
		Set<String> oocSteps = new java.util.LinkedHashSet<>();
		for (AlarmEntity a : alarmRepo.findByEquipmentIdAndStatus(equipmentId, "active")) {
			OffsetDateTime t = a.getEventTime() != null ? a.getEventTime() : a.getCreatedAt();
			if (t == null || t.isBefore(since)) continue;
			String trig = a.getTriggerEvent() == null ? "" : a.getTriggerEvent().toLowerCase();
			if (trig.contains("ooc") || trig.contains("spc")) {
				oocAlarms++;
				if (a.getStep() != null && !a.getStep().isBlank()) oocSteps.add(a.getStep());
			}
		}
		String spcState = oocAlarms >= 3 ? "crit" : oocAlarms >= 1 ? "warn" : "ok";
		String spcValue = oocAlarms > 0 ? oocAlarms + " OOC" : "pass";
		String spcSub = oocSteps.isEmpty() ? "近 24h" : String.join(", ", oocSteps);

		// APC / FDC / DC / EC: derive from latest process event (simulator).
		List<Map<String, Object>> latest = fetchProcessEvents(equipmentId, 1);
		Map<String, Object> e = latest.isEmpty() ? Map.of() : latest.get(0);

		FleetDtos.ModuleStatus apcMod = buildApcModule(e);
		FleetDtos.ModuleStatus fdcMod = buildFdcModule(e);
		FleetDtos.ModuleStatus dcMod = buildDcModule(e);
		FleetDtos.ModuleStatus ecMod = buildEcModule(e);

		List<FleetDtos.ModuleStatus> modules = List.of(
				new FleetDtos.ModuleStatus("SPC", spcState, spcValue, spcSub),
				apcMod, fdcMod, dcMod, ecMod);

		return new FleetDtos.ModulesResponse(equipmentId, now, modules);
	}

	@SuppressWarnings("unchecked")
	private static FleetDtos.ModuleStatus buildApcModule(Map<String, Object> e) {
		Map<String, Object> apc = e.get("APC") instanceof Map<?, ?> m ? (Map<String, Object>) m : Map.of();
		Map<String, Object> params = apc.get("parameters") instanceof Map<?, ?> p ? (Map<String, Object>) p : Map.of();
		// Look at fb_correction; if its absolute value > 1.5 (baseline ~0.9), drift detected.
		Object raw = params.get("fb_correction");
		if (raw instanceof Number n) {
			double fb = n.doubleValue();
			double driftPct = Math.abs(fb - 0.92) / 0.92 * 100;
			if (driftPct >= 20) return new FleetDtos.ModuleStatus("APC", "warn",
					String.format("fb %+.0f%%", fb >= 0.92 ? driftPct : -driftPct),
					"基準 0.92");
		}
		return new FleetDtos.ModuleStatus("APC", "ok", "stable", "active params 正常");
	}

	@SuppressWarnings("unchecked")
	private static FleetDtos.ModuleStatus buildFdcModule(Map<String, Object> e) {
		Map<String, Object> fdc = e.get("FDC") instanceof Map<?, ?> m ? (Map<String, Object>) m : Map.of();
		String classif = String.valueOf(fdc.getOrDefault("classification", "NORMAL")).toUpperCase();
		String state = "FAULT".equals(classif) ? "crit" : "WARNING".equals(classif) ? "warn" : "ok";
		String value = "FAULT".equals(classif) ? "FAULT" : "WARNING".equals(classif) ? "WARNING" : "normal";
		String sub = String.valueOf(fdc.getOrDefault("fault_code", ""));
		if (sub.isBlank() || "null".equals(sub)) sub = "no anomaly";
		return new FleetDtos.ModuleStatus("FDC", state, value, sub);
	}

	private static FleetDtos.ModuleStatus buildDcModule(Map<String, Object> e) {
		// DC isn't currently flagged independently; show pass when there is a recent event.
		boolean hasEvent = e.get("DC") instanceof Map<?, ?>;
		return new FleetDtos.ModuleStatus("DC", "ok", hasEvent ? "pass" : "—",
				hasEvent ? "全部感測正常" : "近期無資料");
	}

	@SuppressWarnings("unchecked")
	private static FleetDtos.ModuleStatus buildEcModule(Map<String, Object> e) {
		Map<String, Object> ec = e.get("EC") instanceof Map<?, ?> m ? (Map<String, Object>) m : Map.of();
		Map<String, Object> consts = ec.get("constants") instanceof Map<?, ?> c ? (Map<String, Object>) c : Map.of();
		int alerts = 0, drifts = 0;
		String firstAlert = null;
		for (Map.Entry<String, Object> entry : consts.entrySet()) {
			if (!(entry.getValue() instanceof Map<?, ?> v)) continue;
			String status = String.valueOf(((Map<String, Object>) v).getOrDefault("status", "NORMAL")).toUpperCase();
			if ("ALERT".equals(status)) {
				alerts++;
				if (firstAlert == null) firstAlert = entry.getKey();
			} else if ("DRIFT".equals(status)) {
				drifts++;
				if (firstAlert == null) firstAlert = entry.getKey();
			}
		}
		String state = alerts > 0 ? "crit" : drifts > 0 ? "warn" : "ok";
		String value = alerts > 0 ? alerts + " alert" : drifts > 0 ? drifts + " drift" : "stable";
		String sub = firstAlert != null ? firstAlert : "constants 正常";
		return new FleetDtos.ModuleStatus("EC", state, value, sub);
	}

	@SuppressWarnings({"unchecked", "rawtypes"})
	public FleetDtos.SpcTraceResponse computeSpcTrace(String equipmentId, int limit) {
		OffsetDateTime now = OffsetDateTime.now(ZoneOffset.UTC);
		List<Map<String, Object>> events = fetchProcessEvents(equipmentId, limit);

		// Process events are newest-first from the simulator; reverse for chart x-axis.
		List<Map<String, Object>> ordered = new ArrayList<>(events);
		java.util.Collections.reverse(ordered);

		Map<String, List<Double>> valuesByChart = new LinkedHashMap<>();
		Map<String, List<OffsetDateTime>> timesByChart = new LinkedHashMap<>();
		Map<String, double[]> limitsByChart = new HashMap<>(); // {ucl, lcl}

		String[] keys = {"c_chart", "p_chart", "r_chart"};
		for (String k : keys) {
			valuesByChart.put(k, new ArrayList<>());
			timesByChart.put(k, new ArrayList<>());
		}

		for (Map<String, Object> ev : ordered) {
			OffsetDateTime t = parseInstant(ev.get("eventTime"));
			Map<String, Object> spc = ev.get("SPC") instanceof Map<?, ?> m ? (Map<String, Object>) m : Map.of();
			Map<String, Object> charts = spc.get("charts") instanceof Map<?, ?> c ? (Map<String, Object>) c : Map.of();
			for (String k : keys) {
				if (!(charts.get(k) instanceof Map<?, ?> ch)) continue;
				Object v = ((Map<String, Object>) ch).get("value");
				if (!(v instanceof Number n)) continue;
				valuesByChart.get(k).add(n.doubleValue());
				if (t != null) timesByChart.get(k).add(t);
				if (!limitsByChart.containsKey(k)) {
					double ucl = ((Map<String, Object>) ch).get("ucl") instanceof Number un ? un.doubleValue() : 0;
					double lcl = ((Map<String, Object>) ch).get("lcl") instanceof Number ln ? ln.doubleValue() : 0;
					limitsByChart.put(k, new double[] { ucl, lcl });
				}
			}
		}

		List<FleetDtos.SpcTrace> out = new ArrayList<>();
		for (String k : keys) {
			List<Double> vs = valuesByChart.get(k);
			if (vs.isEmpty()) continue;
			double[] lim = limitsByChart.getOrDefault(k, new double[]{0, 0});
			double target = vs.stream().mapToDouble(Double::doubleValue).average().orElse(0);
			out.add(new FleetDtos.SpcTrace(k, vs, timesByChart.get(k), lim[0], lim[1], target));
		}
		return new FleetDtos.SpcTraceResponse(equipmentId, now, out);
	}

	private static String severityToLane(String severity) {
		if (severity == null) return "warn";
		return switch (severity.toUpperCase()) {
			case "CRITICAL", "HIGH" -> "crit";
			case "MEDIUM", "MED" -> "warn";
			case "LOW" -> "info";
			default -> "warn";
		};
	}

	private static OffsetDateTime parseInstant(Object v) {
		if (v == null) return null;
		String s = String.valueOf(v);
		// 1. Full ISO with offset: "2026-05-01T02:55:38.065Z" / "+08:00"
		try { return OffsetDateTime.parse(s); } catch (Exception ignored) {}
		// 2. Bare instant ending in Z
		try { return java.time.Instant.parse(s).atOffset(ZoneOffset.UTC); } catch (Exception ignored) {}
		// 3. Naive ISO local-datetime ("2026-05-01T02:55:38.065000") — the
		//    simulator emits this. Treat as UTC.
		try { return java.time.LocalDateTime.parse(s).atOffset(ZoneOffset.UTC); } catch (Exception ignored) {}
		return null;
	}

	// ── Phase 3: lineage view ─────────────────────────────────────────

	public FleetDtos.LineageResponse computeLineage(String equipmentId, String lotIdParam) {
		OffsetDateTime now = OffsetDateTime.now(ZoneOffset.UTC);
		List<Map<String, Object>> events = fetchProcessEvents(equipmentId, 200);

		// Group events by lotID (keep insertion order = simulator order = newest first).
		Map<String, List<Map<String, Object>>> byLot = new LinkedHashMap<>();
		for (Map<String, Object> ev : events) {
			String lot = String.valueOf(ev.getOrDefault("lotID", ""));
			if (lot.isBlank()) continue;
			byLot.computeIfAbsent(lot, k -> new ArrayList<>()).add(ev);
		}

		// Build lot summaries (top 10) — duration = oldest→newest event span in min.
		List<FleetDtos.LotSummary> lots = new ArrayList<>();
		for (Map.Entry<String, List<Map<String, Object>>> entry : byLot.entrySet()) {
			if (lots.size() >= 10) break;
			lots.add(buildLotSummary(entry.getKey(), entry.getValue()));
		}

		// Pick selected lot (param if present + valid, else first).
		String chosenLotId = lotIdParam != null && byLot.containsKey(lotIdParam)
				? lotIdParam
				: (lots.isEmpty() ? null : lots.get(0).lotId());

		FleetDtos.SelectedLotDetail selected = null;
		if (chosenLotId != null) {
			List<Map<String, Object>> lotEvents = byLot.get(chosenLotId);
			selected = buildSelectedLotDetail(equipmentId, chosenLotId, lotEvents, events);
		}

		return new FleetDtos.LineageResponse(equipmentId, now, lots, selected);
	}

	private static FleetDtos.LotSummary buildLotSummary(String lotId, List<Map<String, Object>> evs) {
		// evs is newest-first from the simulator.
		String recipe = "";
		String started = "";
		boolean anyOoc = false, anyWarn = false;
		OffsetDateTime first = null, last = null;
		for (Map<String, Object> ev : evs) {
			Map<?, ?> rec = ev.get("RECIPE") instanceof Map<?, ?> r ? r : null;
			if (recipe.isBlank() && rec != null && rec.get("recipe_version") != null) {
				recipe = "v" + rec.get("recipe_version");
			}
			String spc = String.valueOf(ev.getOrDefault("spc_status", "PASS"));
			if ("OOC".equalsIgnoreCase(spc)) anyOoc = true;
			Object rawFdc = ev.get("FDC");
			if (rawFdc instanceof Map<?, ?> fdcMap) {
				Object cf = fdcMap.get("classification");
				String cls = (cf == null ? "NORMAL" : String.valueOf(cf)).toUpperCase();
				if ("FAULT".equals(cls)) anyOoc = true;
				else if ("WARNING".equals(cls)) anyWarn = true;
			}
			OffsetDateTime t = parseInstant(ev.get("eventTime"));
			if (t != null) {
				if (first == null || t.isBefore(first)) first = t;
				if (last == null || t.isAfter(last)) last = t;
			}
		}
		if (last != null) started = last.toString();
		int durationMin = (first != null && last != null)
				? (int) Math.max(1, Duration.between(first, last).toMinutes())
				: evs.size();
		String status = anyOoc ? "ooc" : anyWarn ? "warn" : "ok";
		return new FleetDtos.LotSummary(lotId, recipe, started, evs.size(), durationMin, status);
	}

	@SuppressWarnings("unchecked")
	private FleetDtos.SelectedLotDetail buildSelectedLotDetail(String equipmentId, String lotId,
	                                                           List<Map<String, Object>> lotEvents,
	                                                           List<Map<String, Object>> allEvents) {
		FleetDtos.LotSummary summary = buildLotSummary(lotId, lotEvents);
		Map<String, Object> latest = lotEvents.isEmpty() ? Map.of() : lotEvents.get(0);

		// ── Lineage nodes ─────────────────────────────────────
		List<FleetDtos.LineageNode> inputs = new ArrayList<>();
		List<FleetDtos.LineageNode> processCol = new ArrayList<>();
		List<FleetDtos.LineageNode> outcomes = new ArrayList<>();

		// RECIPE
		Map<String, Object> recipe = latest.get("RECIPE") instanceof Map<?, ?> r ? (Map<String, Object>) r : Map.of();
		String recipeVer = recipe.get("recipe_version") != null ? "v" + recipe.get("recipe_version") : "—";
		inputs.add(new FleetDtos.LineageNode("RECIPE", recipeVer, recipe.get("recipe_name") != null
				? String.valueOf(recipe.get("recipe_name")) : "current recipe", "info", false));

		// EC
		Map<String, Object> ec = latest.get("EC") instanceof Map<?, ?> e ? (Map<String, Object>) e : Map.of();
		Map<String, Object> consts = ec.get("constants") instanceof Map<?, ?> c ? (Map<String, Object>) c : Map.of();
		String ecState = "ok";
		String ecSub = "constants 正常";
		for (Map.Entry<String, Object> e : consts.entrySet()) {
			if (!(e.getValue() instanceof Map<?, ?> m)) continue;
			String st = String.valueOf(((Map<String, Object>) m).getOrDefault("status", "NORMAL")).toUpperCase();
			if ("ALERT".equals(st)) {
				ecState = "crit";
				ecSub = e.getKey() + " ALERT";
				break;
			} else if ("DRIFT".equals(st) && "ok".equals(ecState)) {
				ecState = "warn";
				ecSub = e.getKey() + " 偏離";
			}
		}
		inputs.add(new FleetDtos.LineageNode("EC", "EC constants", ecSub, ecState, false));

		// FDC
		Map<String, Object> fdc = latest.get("FDC") instanceof Map<?, ?> f ? (Map<String, Object>) f : Map.of();
		String classif = String.valueOf(fdc.getOrDefault("classification", "NORMAL")).toUpperCase();
		String fdcState = "FAULT".equals(classif) ? "crit" : "WARNING".equals(classif) ? "warn" : "ok";
		String fdcSub = String.valueOf(fdc.getOrDefault("fault_code", ""));
		if (fdcSub.isBlank() || "null".equals(fdcSub)) fdcSub = "no anomaly";
		inputs.add(new FleetDtos.LineageNode("FDC", "FDC " + classif, fdcSub, fdcState, false));

		// TOOL — pull score/health from listEquipment for visual continuity.
		FleetDtos.Equipment eqRow = listEquipment(24).equipment().stream()
				.filter(x -> x.id().equals(equipmentId)).findFirst().orElse(null);
		String toolState = eqRow != null
				? (eqRow.health().equals("healthy") ? "ok" : eqRow.health())
				: "ok";
		String toolSub = eqRow != null ? "health " + eqRow.score() + "/100" : "—";
		processCol.add(new FleetDtos.LineageNode("TOOL", equipmentId, toolSub, toolState, true));

		// LOT
		processCol.add(new FleetDtos.LineageNode("LOT", lotId,
				summary.durationMin() + " min · " + summary.events() + " 事件",
				summary.status().equals("ooc") ? "crit" : summary.status().equals("warn") ? "warn" : "ok",
				false));

		// STEPS
		java.util.LinkedHashSet<String> steps = new java.util.LinkedHashSet<>();
		String oocStep = null;
		for (Map<String, Object> ev : lotEvents) {
			String step = String.valueOf(ev.getOrDefault("step", ""));
			if (!step.isBlank()) steps.add(step);
			if ("OOC".equalsIgnoreCase(String.valueOf(ev.getOrDefault("spc_status", ""))) && oocStep == null) {
				oocStep = step;
			}
		}
		String stepsValue = steps.isEmpty() ? "—"
				: steps.size() == 1 ? steps.iterator().next()
				: steps.iterator().next() + " → " + new ArrayList<>(steps).get(steps.size() - 1);
		processCol.add(new FleetDtos.LineageNode("STEPS", stepsValue,
				oocStep != null ? "OOC at " + oocStep : steps.size() + " steps",
				oocStep != null ? "crit" : "ok", false));

		// SPC outcome
		int oocInLot = 0;
		for (Map<String, Object> ev : lotEvents) {
			if ("OOC".equalsIgnoreCase(String.valueOf(ev.getOrDefault("spc_status", "PASS")))) oocInLot++;
		}
		outcomes.add(new FleetDtos.LineageNode("SPC",
				oocInLot > 0 ? "OOC × " + oocInLot : "pass",
				oocInLot > 0 ? "本 LOT 累計 OOC" : "全部 chart 在限",
				oocInLot > 0 ? "crit" : "ok", false));

		// APC outcome — fb_correction summary.
		Map<String, Object> apc = latest.get("APC") instanceof Map<?, ?> a ? (Map<String, Object>) a : Map.of();
		Map<String, Object> apcParams = apc.get("parameters") instanceof Map<?, ?> p ? (Map<String, Object>) p : Map.of();
		Object fbRaw = apcParams.get("fb_correction");
		String apcValue = "stable";
		String apcSub = "active params 正常";
		String apcState = "ok";
		if (fbRaw instanceof Number fbNum) {
			double fb = fbNum.doubleValue();
			double driftPct = (fb - 0.92) / 0.92 * 100;
			apcValue = String.format("fb=%.2f", fb);
			apcSub = String.format("基準 0.92 · %+.0f%%", driftPct);
			if (Math.abs(driftPct) >= 50) apcState = "crit";
			else if (Math.abs(driftPct) >= 20) apcState = "warn";
		}
		outcomes.add(new FleetDtos.LineageNode("APC", apcValue, apcSub, apcState, false));

		// DC outcome
		Map<String, Object> dc = latest.get("DC") instanceof Map<?, ?> d ? (Map<String, Object>) d : Map.of();
		boolean dcHasParams = dc.get("parameters") instanceof Map<?, ?>;
		outcomes.add(new FleetDtos.LineageNode("DC",
				dcHasParams ? "pass" : "—",
				dcHasParams ? "全部感測正常" : "近期無資料", "ok", false));

		FleetDtos.LineageFlow flow = new FleetDtos.LineageFlow(inputs, processCol, outcomes);

		// ── Parameters table ─────────────────────────────────
		List<FleetDtos.ParameterRow> params = buildParameterRows(latest, allEvents);

		return new FleetDtos.SelectedLotDetail(summary, flow, params);
	}

	@SuppressWarnings("unchecked")
	private List<FleetDtos.ParameterRow> buildParameterRows(Map<String, Object> latest,
	                                                        List<Map<String, Object>> allEvents) {
		// Active APC params + key DC sensors + key EC constants.
		String[] apcKeys = {"fb_correction", "rf_power_bias", "etch_time_offset", "gas_flow_comp", "ff_correction"};
		String[] dcKeys = {"chamber_pressure", "esc_zone1_temp", "rf_forward_power", "bias_voltage_v", "cf4_flow_sccm"};
		String[] ecKeys = {"ec_temp_03", "ec_pressure_main"};

		Map<String, Object> apc = latest.get("APC") instanceof Map<?, ?> a ? (Map<String, Object>) a : Map.of();
		Map<String, Object> apcParams = apc.get("parameters") instanceof Map<?, ?> p ? (Map<String, Object>) p : Map.of();
		Map<String, Object> dc = latest.get("DC") instanceof Map<?, ?> d ? (Map<String, Object>) d : Map.of();
		Map<String, Object> dcParams = dc.get("parameters") instanceof Map<?, ?> p ? (Map<String, Object>) p : Map.of();
		Map<String, Object> ec = latest.get("EC") instanceof Map<?, ?> e ? (Map<String, Object>) e : Map.of();
		Map<String, Object> ecConsts = ec.get("constants") instanceof Map<?, ?> c ? (Map<String, Object>) c : Map.of();

		List<FleetDtos.ParameterRow> rows = new ArrayList<>();
		for (String k : apcKeys) {
			if (!apcParams.containsKey(k)) continue;
			rows.add(buildParamRow(k, "APC", apcParams.get(k), allEvents,
					ev -> pickNestedParam(ev, "APC", k)));
		}
		for (String k : dcKeys) {
			if (!dcParams.containsKey(k)) continue;
			rows.add(buildParamRow(k, "DC", dcParams.get(k), allEvents,
					ev -> pickNestedParam(ev, "DC", k)));
		}
		for (String k : ecKeys) {
			if (!ecConsts.containsKey(k)) continue;
			Object v = ecConsts.get(k);
			if (v instanceof Map<?, ?> m) v = ((Map<String, Object>) m).get("value");
			rows.add(buildParamRow(k, "EC", v, allEvents, ev -> pickEcConst(ev, k)));
		}

		// Sort: crit → warn → ok
		rows.sort(Comparator.comparingInt(p -> "crit".equals(p.state()) ? 0 : "warn".equals(p.state()) ? 1 : 2));
		return rows;
	}

	private FleetDtos.ParameterRow buildParamRow(String name, String group, Object latestVal,
	                                             List<Map<String, Object>> allEvents,
	                                             java.util.function.Function<Map<String, Object>, Object> picker) {
		Double v = toDouble(latestVal);
		List<Double> history = new ArrayList<>();
		for (Map<String, Object> ev : allEvents) {
			Double hv = toDouble(picker.apply(ev));
			if (hv != null) history.add(hv);
			if (history.size() >= 10) break;
		}
		java.util.Collections.reverse(history);
		double baseline = history.isEmpty() ? (v == null ? 0 : v)
				: history.subList(0, Math.min(history.size(), 5)).stream()
						.mapToDouble(Double::doubleValue).average().orElse(0);
		double current = v == null ? baseline : v;
		double driftPct = baseline != 0 ? (current - baseline) / Math.abs(baseline) * 100 : 0;
		String state = Math.abs(driftPct) >= 50 ? "crit" : Math.abs(driftPct) >= 20 ? "warn" : "ok";
		String delta = String.format("%+.0f%%", driftPct);
		return new FleetDtos.ParameterRow(name, group, v, baseline, delta, state, history);
	}

	/** Reach into ev[group].parameters[key] safely. group ∈ APC|DC. */
	@SuppressWarnings("unchecked")
	private static Object pickNestedParam(Map<String, Object> ev, String group, String key) {
		Object g = ev.get(group);
		if (!(g instanceof Map<?, ?> gMap)) return null;
		Object params = ((Map<String, Object>) gMap).get("parameters");
		if (!(params instanceof Map<?, ?> pMap)) return null;
		return ((Map<String, Object>) pMap).get(key);
	}

	/** Reach into ev.EC.constants[key] (which may itself be {value, status, ...}). */
	@SuppressWarnings("unchecked")
	private static Object pickEcConst(Map<String, Object> ev, String key) {
		Object ec = ev.get("EC");
		if (!(ec instanceof Map<?, ?> ecMap)) return null;
		Object consts = ((Map<String, Object>) ecMap).get("constants");
		if (!(consts instanceof Map<?, ?> cMap)) return null;
		Object cv = ((Map<String, Object>) cMap).get(key);
		if (cv instanceof Map<?, ?> mv) return ((Map<String, Object>) mv).get("value");
		return cv;
	}

	private static Double toDouble(Object v) {
		if (v == null) return null;
		if (v instanceof Number n) return n.doubleValue();
		try { return Double.parseDouble(String.valueOf(v)); } catch (Exception ignored) { return null; }
	}

	@SuppressWarnings("unchecked")
	private List<Map<String, Object>> fetchProcessEvents(String toolId, int limit) {
		try {
			JsonNode root = simulatorClient.get()
					.uri(uri -> uri.path("/api/v1/process/info")
							.queryParam("toolID", toolId)
							.queryParam("limit", limit)
							.build())
					.retrieve()
					.bodyToMono(JsonNode.class)
					.block(Duration.ofSeconds(8));
			if (root == null) return List.of();
			JsonNode events = root.get("events");
			if (events == null || !events.isArray()) return List.of();
			TypeReference<List<Map<String, Object>>> typeRef = new TypeReference<>() {};
			return mapper.convertValue(events, typeRef);
		} catch (Exception ex) {
			log.warn("simulator process_info fetch failed for {}: {}", toolId, ex.toString());
			return List.of();
		}
	}
}
