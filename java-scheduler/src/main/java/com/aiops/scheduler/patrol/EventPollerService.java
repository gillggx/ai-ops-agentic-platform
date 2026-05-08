package com.aiops.scheduler.patrol;

import com.aiops.api.domain.event.EventTypeEntity;
import com.aiops.api.domain.event.EventTypeRepository;
import com.aiops.api.domain.event.GeneratedEventEntity;
import com.aiops.api.domain.event.GeneratedEventRepository;
import com.aiops.scheduler.lock.DistributedLockService;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Phase F — poll the Ontology Simulator for recent events, filter the ones
 * that should fire an event-mode auto_patrol, and persist them as
 * {@code generated_events} rows.
 *
 * <p>Originally this lived in the Python {@code event_poller_service.py}
 * (493 LOC) which was decommissioned alongside the rest of fastapi-backend
 * during Phase 8-A cutover. Without a replacement, every event-mode
 * auto_patrol simply never fired — the simulator emitted plenty of OOC
 * events but nobody was ingesting them into Java. This service closes
 * that gap.
 *
 * <p>How it works:
 * <ol>
 *   <li>Every 30 s, fetch up to 200 events from the simulator since the
 *       last successful poll's high-water mark.</li>
 *   <li>For each event whose {@code spc_status == "OOC"}, look up the
 *       canonical "OOC" event_type row (seeded). If absent, log + skip.</li>
 *   <li>Write a {@code generated_events} row with {@code mapped_parameters}
 *       carrying equipment_id / lot_id / step / event_time. The
 *       InternalGeneratedEventController's @Transactional save hook fans
 *       out via EventDispatchService.dispatchGeneratedEvent — but we're
 *       writing directly here, so we invoke the dispatcher manually.</li>
 *   <li>Advance the watermark to the latest seen eventTime.</li>
 * </ol>
 *
 * <p>Out of scope (vs the original Python): per-tool / per-step custom
 * event_type mapping (only the canonical "OOC" maps now), event throttling,
 * idempotency on duplicates beyond the watermark. These were YAGNI for the
 * v1 port; can be added when needed.
 */
@Slf4j
@Service
public class EventPollerService {

	private static final int POLL_LIMIT = 200;
	private static final String OOC_EVENT_TYPE_NAME = "OOC";

	private final SimulatorClient simulatorClient;
	private final EventTypeRepository eventTypeRepo;
	private final GeneratedEventRepository generatedEventRepo;
	private final EventDispatchService dispatchService;
	private final ObjectMapper objectMapper;
	private final DistributedLockService lockService;

	/** ISO-8601 string of the latest eventTime we've successfully ingested.
	 *  Held in memory; on cold start we fall back to "now - 5 minutes" so
	 *  we don't replay the entire simulator history every restart. */
	private final AtomicReference<String> watermark = new AtomicReference<>(null);

	public EventPollerService(SimulatorClient simulatorClient,
	                          EventTypeRepository eventTypeRepo,
	                          GeneratedEventRepository generatedEventRepo,
	                          EventDispatchService dispatchService,
	                          ObjectMapper objectMapper,
	                          DistributedLockService lockService) {
		this.simulatorClient = simulatorClient;
		this.eventTypeRepo = eventTypeRepo;
		this.generatedEventRepo = generatedEventRepo;
		this.dispatchService = dispatchService;
		this.objectMapper = objectMapper;
		this.lockService = lockService;
	}

	@PostConstruct
	void init() {
		// Cold-start guard: pretend the last poll happened 5 min ago so we
		// catch any genuinely new events but don't replay the entire
		// simulator history (hours/days of archived OOC).
		String iso = OffsetDateTime.now(ZoneOffset.UTC)
				.minusMinutes(5)
				.format(DateTimeFormatter.ISO_OFFSET_DATE_TIME);
		watermark.set(iso);
		log.info("EventPollerService init: watermark={}", iso);
	}

	// Cron form is more reliably picked up by Spring's @EnableScheduling
	// scanner than fixedDelay across some classpath/proxy combos. "*/30
	// * * * * *" = every 30 seconds, every minute.
	@Scheduled(cron = "*/30 * * * * *")
	public void poll() {
		// Phase 3 — only one scheduler pod polls per tick. TTL 60s gives
		// 2× safety over the 30s tick interval; if a pod crashes mid-poll,
		// the lock auto-releases by the second-next tick.
		lockService.runWithLock("event_poller", Duration.ofSeconds(60), this::doPoll);
	}

	@Transactional
	void doPoll() {
		log.debug("EventPoller: tick");
		String since = watermark.get();
		List<Map<String, Object>> events;
		try {
			events = simulatorClient.listRecentEvents(since, POLL_LIMIT);
		} catch (Exception ex) {
			log.warn("EventPoller: simulator fetch failed: {}", ex.getMessage());
			return;
		}
		if (events.isEmpty()) {
			log.debug("EventPoller: no events since {}", since);
			return;
		}

		// Resolve OOC event_type once per poll batch.
		Optional<EventTypeEntity> oocEventTypeOpt = eventTypeRepo.findByName(OOC_EVENT_TYPE_NAME);
		if (oocEventTypeOpt.isEmpty()) {
			log.warn("EventPoller: no event_type row named '{}' — seed it first; skipping ingest",
					OOC_EVENT_TYPE_NAME);
			return;
		}
		Long oocEventTypeId = oocEventTypeOpt.get().getId();

		String latestSeen = since;
		int oocCount = 0;
		int dispatchedCount = 0;
		for (Map<String, Object> ev : events) {
			Object evTime = ev.get("eventTime");
			if (evTime instanceof String s && s.compareTo(latestSeen == null ? "" : latestSeen) > 0) {
				latestSeen = s;
			}
			Object spcStatus = ev.get("spc_status");
			if (!"OOC".equals(spcStatus)) continue;
			oocCount++;

			Map<String, Object> mapped = new HashMap<>();
			mapped.put("equipment_id", ev.get("toolID"));
			mapped.put("tool_id", ev.get("toolID"));   // mirror so either name binds
			mapped.put("lot_id", ev.get("lotID"));
			mapped.put("step", ev.get("step"));
			mapped.put("event_time", evTime);
			mapped.put("recipe_id", ev.get("recipeID"));
			mapped.put("apc_id", ev.get("apcID"));
			mapped.put("spc_status", spcStatus);

			String mappedJson;
			try {
				mappedJson = objectMapper.writeValueAsString(mapped);
			} catch (JsonProcessingException jex) {
				log.warn("EventPoller: failed to serialise mapped_parameters: {}", jex.getMessage());
				continue;
			}

			GeneratedEventEntity row = new GeneratedEventEntity();
			row.setEventTypeId(oocEventTypeId);
			// source_skill_id is required NOT NULL; use 0 sentinel for poller-
			// originated events (they aren't tied to a skill execution).
			row.setSourceSkillId(0L);
			row.setMappedParameters(mappedJson);
			row.setSkillConclusion("auto-ingested by EventPoller from simulator");
			row.setStatus("pending");
			GeneratedEventEntity saved;
			try {
				saved = generatedEventRepo.save(row);
			} catch (Exception ex) {
				log.warn("EventPoller: save generated_events failed: {}", ex.getMessage());
				continue;
			}

			// Hand off to the dispatcher (same async path the
			// /internal/generated-events controller uses).
			try {
				dispatchService.dispatchGeneratedEvent(saved.getEventTypeId(), saved.getMappedParameters());
				dispatchedCount++;
			} catch (Exception ex) {
				log.warn("EventPoller: dispatch failed for generated_event id={}: {}",
						saved.getId(), ex.getMessage());
			}
		}

		if (latestSeen != null && (since == null || latestSeen.compareTo(since) > 0)) {
			watermark.set(latestSeen);
		}
		if (oocCount > 0) {
			log.info("EventPoller: scanned={} OOC={} dispatched={} watermark={}",
					events.size(), oocCount, dispatchedCount, latestSeen);
		}
	}
}
