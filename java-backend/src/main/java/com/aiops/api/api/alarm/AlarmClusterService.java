package com.aiops.api.api.alarm;

import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.domain.pipeline.PipelineRunEntity;
import com.aiops.api.domain.pipeline.PipelineRunRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Cluster-first view of the Alarm Center. SPEC §2.2 — pure derivation
 * from {@code alarms} (no separate cluster table). Groups by
 * equipment_id; sparkline / KPIs are computed in memory because the
 * windowed alarm list is small (a few hundred rows).
 */
@Service
public class AlarmClusterService {

	private static final int SPARK_BUCKETS = 10;
	private static final Pattern EQP_PATTERN = Pattern.compile("EQP-?(\\d+)");

	private final AlarmRepository alarmRepo;
	private final PipelineRunRepository runRepo;

	public AlarmClusterService(AlarmRepository alarmRepo, PipelineRunRepository runRepo) {
		this.alarmRepo = alarmRepo;
		this.runRepo = runRepo;
	}

	public AlarmClusterDtos.ClusterListResponse computeClusters(int sinceHours, String statusFilter) {
		OffsetDateTime now = OffsetDateTime.now(ZoneOffset.UTC);
		OffsetDateTime since = now.minusHours(Math.max(sinceHours, 1));

		List<AlarmEntity> rows = alarmRepo.findByEventTimeAfterOrderByEventTimeDesc(since);
		List<AlarmEntity> filtered = rows.stream()
				.filter(a -> statusFilter == null || statusFilter.isBlank()
						|| statusFilter.equalsIgnoreCase(a.getStatus()))
				.toList();

		// Group by equipment_id preserving insertion order (highest severity → highest count later)
		Map<String, List<AlarmEntity>> grouped = new LinkedHashMap<>();
		for (AlarmEntity a : filtered) {
			String key = a.getEquipmentId() == null || a.getEquipmentId().isBlank()
					? "__unbound__" : a.getEquipmentId();
			grouped.computeIfAbsent(key, k -> new ArrayList<>()).add(a);
		}

		List<AlarmClusterDtos.Cluster> clusters = new ArrayList<>();
		for (Map.Entry<String, List<AlarmEntity>> e : grouped.entrySet()) {
			clusters.add(buildCluster(e.getKey(), e.getValue(), since, now));
		}

		// Sort: severity desc → count desc → last_at desc
		clusters.sort(Comparator.<AlarmClusterDtos.Cluster>comparingInt(
						c -> -severityRank(c.severity()))
				.thenComparingInt(c -> -c.count())
				.thenComparing(c -> c.lastAt(), Comparator.nullsLast(Comparator.reverseOrder())));

		return new AlarmClusterDtos.ClusterListResponse(
				sinceHours + "h", now, filtered.size(), clusters);
	}

	public AlarmClusterDtos.Kpis computeKpis(int sinceHours) {
		OffsetDateTime now = OffsetDateTime.now(ZoneOffset.UTC);
		OffsetDateTime since = now.minusHours(Math.max(sinceHours, 1));

		List<AlarmEntity> windowed = alarmRepo.findByEventTimeAfterOrderByEventTimeDesc(since);
		int active = 0, high = 0;
		Set<String> openTools = new HashSet<>();
		long resolvedCount = 0;
		long resolvedMillisSum = 0;
		int lowSev = 0, medSev = 0, highSev = 0;
		for (AlarmEntity a : windowed) {
			String s = a.getStatus() == null ? "" : a.getStatus().toLowerCase();
			if ("active".equals(s)) {
				active++;
				if (a.getEquipmentId() != null && !a.getEquipmentId().isBlank()) {
					openTools.add(a.getEquipmentId());
				}
				int rank = severityRank(a.getSeverity());
				if (rank >= 3) high++;
				if (rank >= 3) highSev++;
				else if (rank == 2) medSev++;
				else lowSev++;
			} else if ("resolved".equals(s) && a.getResolvedAt() != null && a.getEventTime() != null) {
				resolvedCount++;
				resolvedMillisSum += Duration.between(a.getEventTime(), a.getResolvedAt()).toMillis();
			}
		}
		Integer mttrMin = resolvedCount == 0 ? null
				: (int) (resolvedMillisSum / resolvedCount / 60_000);

		// auto-check runs (last hour, regardless of sinceHours — the strip
		// shows realtime AI throughput).
		OffsetDateTime hourAgo = now.minusHours(1);
		List<PipelineRunEntity> runs;
		try {
			runs = runRepo.findAutoCheckRunsSince(hourAgo);
		} catch (Exception ex) {
			runs = List.of();
		}
		int runCount = runs.size();
		Double avgLatency = null;
		if (runCount > 0) {
			long totalMs = 0;
			int sampled = 0;
			for (PipelineRunEntity r : runs) {
				if (r.getStartedAt() != null && r.getFinishedAt() != null) {
					long ms = Duration.between(r.getStartedAt(), r.getFinishedAt()).toMillis();
					// finished_at < started_at appears for runs that the
					// scheduler stamped before kicking off the executor —
					// treat as zero so the strip never shows -0.0s.
					if (ms < 0) ms = 0;
					totalMs += ms;
					sampled++;
				}
			}
			if (sampled > 0) avgLatency = (totalMs / (double) sampled) / 1000.0;
		}

		// Health score: 100 − (high*5 + med*2 + low*1), clamped.
		int score = 100 - (highSev * 5 + medSev * 2 + lowSev);
		if (score < 0) score = 0;
		if (score > 100) score = 100;

		return new AlarmClusterDtos.Kpis(active, openTools.size(), high, mttrMin,
				runCount, avgLatency, score);
	}

	@Transactional
	public AlarmClusterDtos.ClusterAckResponse ackCluster(String equipmentId, String operator) {
		List<AlarmEntity> openOnes = alarmRepo.findByEquipmentIdAndStatus(equipmentId, "active");
		OffsetDateTime now = OffsetDateTime.now(ZoneOffset.UTC);
		for (AlarmEntity a : openOnes) {
			a.setStatus("acknowledged");
			a.setAcknowledgedBy(operator);
			a.setAcknowledgedAt(now);
		}
		if (!openOnes.isEmpty()) alarmRepo.saveAll(openOnes);
		return new AlarmClusterDtos.ClusterAckResponse(equipmentId, openOnes.size());
	}

	private AlarmClusterDtos.Cluster buildCluster(String equipmentId,
	                                              List<AlarmEntity> alarms,
	                                              OffsetDateTime since,
	                                              OffsetDateTime now) {
		int count = alarms.size();
		int open = 0, ack = 0, resolved = 0;
		Set<String> lots = new HashSet<>();
		java.util.LinkedHashSet<String> orderedEvents = new java.util.LinkedHashSet<>();
		OffsetDateTime first = null, last = null;
		int sevRank = 0;
		AlarmEntity latestActive = null;

		for (AlarmEntity a : alarms) {
			String s = a.getStatus() == null ? "" : a.getStatus().toLowerCase();
			switch (s) {
				case "active" -> open++;
				case "acknowledged" -> ack++;
				case "resolved" -> resolved++;
				default -> {}
			}
			if (a.getLotId() != null && !a.getLotId().isBlank()) lots.add(a.getLotId());
			if (a.getTriggerEvent() != null && !a.getTriggerEvent().isBlank()) {
				orderedEvents.add(a.getTriggerEvent());
			}
			OffsetDateTime t = a.getEventTime() != null ? a.getEventTime() : a.getCreatedAt();
			if (t != null) {
				if (first == null || t.isBefore(first)) first = t;
				if (last == null || t.isAfter(last)) last = t;
			}
			int r = severityRank(a.getSeverity());
			if (r > sevRank) sevRank = r;
			if ("active".equals(s) && (latestActive == null
					|| (a.getEventTime() != null && latestActive.getEventTime() != null
							&& a.getEventTime().isAfter(latestActive.getEventTime())))) {
				latestActive = a;
			}
		}

		// Sparkline: bucket alarms across the since→now window.
		long winMs = Math.max(Duration.between(since, now).toMillis(), 1);
		int[] buckets = new int[SPARK_BUCKETS];
		for (AlarmEntity a : alarms) {
			OffsetDateTime t = a.getEventTime() != null ? a.getEventTime() : a.getCreatedAt();
			if (t == null) continue;
			long offset = Duration.between(since, t).toMillis();
			int idx = (int) Math.min(SPARK_BUCKETS - 1,
					Math.max(0, offset * SPARK_BUCKETS / winMs));
			buckets[idx]++;
		}
		List<Integer> spark = new ArrayList<>(SPARK_BUCKETS);
		for (int v : buckets) spark.add(v);

		AlarmEntity rep = latestActive != null ? latestActive : alarms.get(0);
		String title = count == 1
				? rep.getTitle()
				: equipmentId + " 連續異常（" + count + " 件，" + orderedEvents.size() + " 種告警）";
		String summary = rep.getSummary();

		List<Long> alarmIds = alarms.stream().map(AlarmEntity::getId).toList();

		return new AlarmClusterDtos.Cluster(
				equipmentId,
				equipmentId,
				deriveBay(equipmentId),
				severityName(sevRank),
				title,
				summary,
				new ArrayList<>(orderedEvents),
				count, open, ack, resolved,
				lots.size(),
				first, last,
				spark,
				deriveCause(orderedEvents),
				null,
				alarmIds);
	}

	/** Bay derivation from equipment_id. EQP-01..10 → A, 11..20 → B,
	 *  21..30 → C; anything else → null. */
	static String deriveBay(String equipmentId) {
		if (equipmentId == null) return null;
		Matcher m = EQP_PATTERN.matcher(equipmentId);
		if (!m.find()) return null;
		try {
			int n = Integer.parseInt(m.group(1));
			if (n >= 1 && n <= 10) return "A";
			if (n >= 11 && n <= 20) return "B";
			if (n >= 21 && n <= 30) return "C";
		} catch (NumberFormatException ignored) {}
		return null;
	}

	/** Crude cause label from trigger event names. v1 — no model. */
	private static String deriveCause(java.util.LinkedHashSet<String> events) {
		if (events.isEmpty()) return null;
		for (String e : events) {
			String lc = e.toLowerCase();
			if (lc.contains("ooc") || lc.contains("spc")) return "SPC drift";
			if (lc.contains("particle")) return "Particle excursion";
			if (lc.contains("etch")) return "Etch rate drift";
			if (lc.contains("temp") || lc.contains("sensor")) return "Sensor drift";
			if (lc.contains("throughput")) return "Throughput drop";
		}
		return events.iterator().next();
	}

	static int severityRank(String severity) {
		if (severity == null) return 0;
		return switch (severity.toUpperCase()) {
			case "CRITICAL" -> 4;
			case "HIGH" -> 3;
			case "MEDIUM", "MED" -> 2;
			case "LOW" -> 1;
			default -> 0;
		};
	}

	static String severityName(int rank) {
		return switch (rank) {
			case 4 -> "critical";
			case 3 -> "high";
			case 2 -> "med";
			case 1 -> "low";
			default -> "low";
		};
	}
}
