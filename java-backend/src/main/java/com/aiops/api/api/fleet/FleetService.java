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

		// total_events not available locally — keep at 0; v2 hits ontology /summary.
		return new FleetDtos.FleetStats(
				roundOne(fleetOocRate), oocEvents, 0, fdcAlerts,
				openAlarms, affectedLots.size(), critCount, warnCount, now);
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

		// score = 100 − (oocPct·2 + openAlarms·3 + fdc·2), clamped.
		// Rate-based (not absolute count) so a tool with 50 OOC out of 300
		// events doesn't auto-zero the score. Tuned for ~10-30% rate range.
		int penalty = (int) Math.round(oocPct * 2 + openAlarms * 3.0 + fdc * 2.0);
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
		long winMs = Math.max(Duration.between(since, now).toMillis(), 1);
		int[] buckets = new int[SPARK_BUCKETS];
		for (AlarmEntity a : alarms) {
			OffsetDateTime t = a.getEventTime() != null ? a.getEventTime() : a.getCreatedAt();
			if (t == null) continue;
			String trig = a.getTriggerEvent() == null ? "" : a.getTriggerEvent().toLowerCase();
			if (!(trig.contains("ooc") || trig.contains("spc"))) continue;
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
}
