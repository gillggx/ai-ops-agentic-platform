package com.aiops.api.api.fleet;

import com.aiops.api.domain.alarm.AlarmEntity;
import com.aiops.api.domain.alarm.AlarmRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;

/**
 * Per-equipment detail views for the Fleet Dashboard — timeline / module
 * status / SPC trace / lot lineage.
 *
 * <p>Extracted from {@code FleetService} 2026-05-23 as part of the Phase 12
 * Java OOP refactor. The four endpoints share the same simulator events
 * fetch + alarm aggregation pattern but build very different response shapes
 * — keeping them together here keeps the per-equipment story coherent
 * (and out of the fleet-wide {@link FleetRosterService}).
 *
 * <p>Depends on {@link FleetRosterService} for one cross-call: the lot
 * lineage view reuses the tool's health/score from the roster so visual
 * continuity with the dashboard is preserved.
 */
@Slf4j
@Service
public class FleetEquipmentDetailService {

	private final AlarmRepository alarmRepo;
	private final FleetSimulatorClient simulator;
	private final FleetRosterService rosterService;

	public FleetEquipmentDetailService(AlarmRepository alarmRepo,
	                                   FleetSimulatorClient simulator,
	                                   FleetRosterService rosterService) {
		this.alarmRepo = alarmRepo;
		this.simulator = simulator;
		this.rosterService = rosterService;
	}

	// ══════════════════════════════════════════════════════════════════════
	// Timeline
	// ══════════════════════════════════════════════════════════════════════

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

		// Lane: lot — only OOC lots (one dot per problem-LOT). Healthy lots
		// fire constantly in this simulator and would saturate the strip
		// (~600 dots in earlier render). Whoever wants the full LOT history
		// uses 「製程溯源」/「LOT scrubber」 instead.
		// Lane: recipe — disabled. The simulator emits a different
		// recipe_version per event (v265, v269, v273…) rather than holding
		// a tool's version stable, so any "diff vs last seen" heuristic
		// emits hundreds of spurious changes. Re-enable once the simulator
		// exposes a stable per-tool recipe state.
		List<Map<String, Object>> events500 = simulator.fetchProcessEvents(equipmentId, 500);
		Set<String> seenLots = new LinkedHashSet<>();
		for (Map<String, Object> ev : events500) {
			OffsetDateTime t = parseInstant(ev.get("eventTime"));
			if (t == null || t.isBefore(since)) continue;
			String lot = String.valueOf(ev.getOrDefault("lotID", ""));
			if (lot.isBlank() || seenLots.contains(lot)) continue;
			String spcStatus = String.valueOf(ev.getOrDefault("spc_status", "PASS"));
			if (!"OOC".equalsIgnoreCase(spcStatus)) continue; // skip pass lots
			seenLots.add(lot);
			events.add(new FleetDtos.TimelineEvent(t, "lot", "crit",
					lot, "STEP " + ev.getOrDefault("step", "?")));
		}

		// Sort newest → oldest for transport stability.
		events.sort(Comparator.comparing(
				FleetDtos.TimelineEvent::t,
				Comparator.nullsLast(Comparator.reverseOrder())));

		return new FleetDtos.TimelineResponse(equipmentId, since, now, events);
	}

	// ══════════════════════════════════════════════════════════════════════
	// Modules (SPC / APC / FDC / DC / EC)
	// ══════════════════════════════════════════════════════════════════════

	public FleetDtos.ModulesResponse computeModules(String equipmentId, int sinceHours) {
		OffsetDateTime now = OffsetDateTime.now(ZoneOffset.UTC);
		OffsetDateTime since = now.minusHours(Math.max(sinceHours, 1));

		// SPC: count OOC alarms (or simulator OOC events).
		int oocAlarms = 0;
		Set<String> oocSteps = new LinkedHashSet<>();
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
		List<Map<String, Object>> latest = simulator.fetchProcessEvents(equipmentId, 1);
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

	// ══════════════════════════════════════════════════════════════════════
	// SPC trace
	// ══════════════════════════════════════════════════════════════════════

	@SuppressWarnings({"unchecked", "rawtypes"})
	public FleetDtos.SpcTraceResponse computeSpcTrace(String equipmentId, int limit) {
		OffsetDateTime now = OffsetDateTime.now(ZoneOffset.UTC);
		List<Map<String, Object>> events = simulator.fetchProcessEvents(equipmentId, limit);

		// Process events are newest-first from the simulator; reverse for chart x-axis.
		List<Map<String, Object>> ordered = new ArrayList<>(events);
		Collections.reverse(ordered);

		// Discover chart_names dynamically — different recipes / tools may
		// emit different sets (xbar / R / S / P / C / future …). Hardcoding
		// {C, P, R} hid two of the existing five SPC charts.
		Map<String, List<Double>> valuesByChart = new LinkedHashMap<>();
		Map<String, List<OffsetDateTime>> timesByChart = new LinkedHashMap<>();
		Map<String, double[]> limitsByChart = new HashMap<>(); // {ucl, lcl}

		for (Map<String, Object> ev : ordered) {
			OffsetDateTime t = parseInstant(ev.get("eventTime"));
			Map<String, Object> spc = ev.get("SPC") instanceof Map<?, ?> m ? (Map<String, Object>) m : Map.of();
			Map<String, Object> charts = spc.get("charts") instanceof Map<?, ?> c ? (Map<String, Object>) c : Map.of();
			for (Map.Entry<String, Object> entry : charts.entrySet()) {
				String k = entry.getKey();
				if (!(entry.getValue() instanceof Map<?, ?> ch)) continue;
				Object v = ((Map<String, Object>) ch).get("value");
				if (!(v instanceof Number n)) continue;
				valuesByChart.computeIfAbsent(k, x -> new ArrayList<>()).add(n.doubleValue());
				timesByChart.computeIfAbsent(k, x -> new ArrayList<>());
				if (t != null) timesByChart.get(k).add(t);
				if (!limitsByChart.containsKey(k)) {
					double ucl = ((Map<String, Object>) ch).get("ucl") instanceof Number un ? un.doubleValue() : 0;
					double lcl = ((Map<String, Object>) ch).get("lcl") instanceof Number ln ? ln.doubleValue() : 0;
					limitsByChart.put(k, new double[] { ucl, lcl });
				}
			}
		}

		List<FleetDtos.SpcTrace> out = new ArrayList<>();
		// Stable sort by chart name so the dropdown order doesn't jitter.
		List<String> orderedKeys = new ArrayList<>(valuesByChart.keySet());
		Collections.sort(orderedKeys);
		for (String k : orderedKeys) {
			List<Double> vs = valuesByChart.get(k);
			if (vs.isEmpty()) continue;
			double[] lim = limitsByChart.getOrDefault(k, new double[]{0, 0});
			double target = vs.stream().mapToDouble(Double::doubleValue).average().orElse(0);
			out.add(new FleetDtos.SpcTrace(k, vs, timesByChart.get(k), lim[0], lim[1], target));
		}
		return new FleetDtos.SpcTraceResponse(equipmentId, now, out);
	}

	// ══════════════════════════════════════════════════════════════════════
	// Lot lineage
	// ══════════════════════════════════════════════════════════════════════

	public FleetDtos.LineageResponse computeLineage(String equipmentId, String lotIdParam) {
		OffsetDateTime now = OffsetDateTime.now(ZoneOffset.UTC);
		List<Map<String, Object>> events = simulator.fetchProcessEvents(equipmentId, 200);

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

	@SuppressWarnings("unchecked")
	private static FleetDtos.LotSummary buildLotSummary(String lotId, List<Map<String, Object>> evs) {
		// evs is newest-first from the simulator.
		String recipe = "";
		String started = "";
		boolean anyOoc = false, anyWarn = false;
		OffsetDateTime first = null, last = null;
		String latestStep = "";
		String latestEventTime = "";
		for (int i = 0; i < evs.size(); i++) {
			Map<String, Object> ev = evs.get(i);
			Object rec = ev.get("RECIPE");
			if (recipe.isBlank() && rec instanceof Map<?, ?> recMap) {
				Object rv = ((Map<String, Object>) recMap).get("recipe_version");
				if (rv != null) recipe = "v" + rv;
			}
			String spc = String.valueOf(ev.getOrDefault("spc_status", "PASS"));
			if ("OOC".equalsIgnoreCase(spc)) anyOoc = true;
			Object rawFdc = ev.get("FDC");
			if (rawFdc instanceof Map<?, ?> fdcMap) {
				Object cf = ((Map<String, Object>) fdcMap).get("classification");
				String cls = (cf == null ? "NORMAL" : String.valueOf(cf)).toUpperCase();
				if ("FAULT".equals(cls)) anyOoc = true;
				else if ("WARNING".equals(cls)) anyWarn = true;
			}
			OffsetDateTime t = parseInstant(ev.get("eventTime"));
			if (t != null) {
				if (first == null || t.isBefore(first)) first = t;
				if (last == null || t.isAfter(last)) last = t;
			}
			// First iteration = newest event from simulator. Capture the step
			// + raw eventTime so /api/ontology/topology can be queried (it
			// requires lot + step + eventTime, otherwise 400s).
			if (i == 0) {
				Object stepObj = ev.get("step");
				if (stepObj != null) latestStep = String.valueOf(stepObj);
				Object etRaw = ev.get("eventTime");
				if (etRaw != null) latestEventTime = String.valueOf(etRaw);
			}
		}
		if (last != null) started = last.toString();
		int durationMin = (first != null && last != null)
				? (int) Math.max(1, Duration.between(first, last).toMinutes())
				: evs.size();
		String status = anyOoc ? "ooc" : anyWarn ? "warn" : "ok";
		return new FleetDtos.LotSummary(lotId, recipe, started, evs.size(), durationMin, status,
				latestStep, latestEventTime);
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

		// TOOL — pull score/health from roster for visual continuity with the dashboard.
		FleetDtos.Equipment eqRow = rosterService.listEquipment(24).equipment().stream()
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
		LinkedHashSet<String> steps = new LinkedHashSet<>();
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
	                                              Function<Map<String, Object>, Object> picker) {
		Double v = toDouble(latestVal);
		List<Double> history = new ArrayList<>();
		for (Map<String, Object> ev : allEvents) {
			Double hv = toDouble(picker.apply(ev));
			if (hv != null) history.add(hv);
			if (history.size() >= 10) break;
		}
		Collections.reverse(history);
		double baseline = history.isEmpty() ? (v == null ? 0 : v)
				: history.subList(0, Math.min(history.size(), 5)).stream()
						.mapToDouble(Double::doubleValue).average().orElse(0);
		double current = v == null ? baseline : v;
		double driftPct = baseline != 0 ? (current - baseline) / Math.abs(baseline) * 100 : 0;
		String state = Math.abs(driftPct) >= 50 ? "crit" : Math.abs(driftPct) >= 20 ? "warn" : "ok";
		String delta = String.format("%+.0f%%", driftPct);
		return new FleetDtos.ParameterRow(name, group, v, baseline, delta, state, history);
	}

	// ══════════════════════════════════════════════════════════════════════
	// Helpers
	// ══════════════════════════════════════════════════════════════════════

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
		try { return Instant.parse(s).atOffset(ZoneOffset.UTC); } catch (Exception ignored) {}
		// 3. Naive ISO local-datetime ("2026-05-01T02:55:38.065000") — the
		//    simulator emits this. Treat as UTC.
		try { return LocalDateTime.parse(s).atOffset(ZoneOffset.UTC); } catch (Exception ignored) {}
		return null;
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
}
