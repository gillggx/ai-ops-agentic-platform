package com.aiops.api.domain.notification;

import com.aiops.api.domain.patrol.AutoPatrolEntity;
import com.aiops.api.domain.patrol.AutoPatrolRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Phase 9-A — minimal notification primitive. Inserts a row into
 * notification_inbox so the bell-icon widget can pick it up. Future
 * channels (email / push / slack) plug in here without changing the
 * caller (AutoPatrolExecutor).
 *
 * Template placeholders: {pipeline_run_id}, {top_tools}, {alarm_count}, …
 * resolved against the pipeline run output map. Missing placeholders are
 * left as-is so the user can see what was missing rather than getting a
 * silent empty string.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class NotificationDispatchService {

	private final NotificationInboxRepository inboxRepo;
	private final AutoPatrolRepository patrolRepo;
	private final ObjectMapper objectMapper;

	/**
	 * Render the rule's notification_template against a pipeline run output
	 * payload, then write a row to the owner's inbox. Updates the rule's
	 * last_dispatched_at timestamp on success.
	 *
	 * @param rule       the personal rule that fired
	 * @param runId      execution_logs.id of the pipeline run, for back-link
	 * @param runOutput  result rows / chart spec / aggregates returned by the executor
	 */
	@Transactional
	public void dispatch(AutoPatrolEntity rule, Long runId, Map<String, Object> runOutput) {
		if (rule.getCreatedBy() == null) {
			log.warn("dispatch skipped — rule {} has no owner_user_id (created_by)", rule.getId());
			return;
		}

		String title = rule.getName() != null ? rule.getName() : "Rule fired";
		String template = rule.getNotificationTemplate();
		String body = (template == null || template.isBlank())
				? defaultBody(runOutput)
				: renderTemplate(template, runOutput);

		Map<String, Object> payload = new LinkedHashMap<>();
		payload.put("title", title);
		payload.put("body", body);
		payload.put("rule_id", rule.getId());
		payload.put("run_id", runId);
		Object chartId = runOutput == null ? null : runOutput.get("chart_id");
		if (chartId != null) payload.put("chart_id", chartId);

		String payloadJson;
		try {
			payloadJson = objectMapper.writeValueAsString(payload);
		} catch (Exception e) {
			log.error("dispatch: failed to serialise payload for rule {}: {}", rule.getId(), e.getMessage());
			payloadJson = "{\"title\":\"" + title + "\",\"body\":\"<render error>\"}";
		}

		NotificationInboxEntity row = new NotificationInboxEntity();
		row.setUserId(rule.getCreatedBy());
		row.setRuleId(rule.getId());
		row.setPayload(payloadJson);
		row.setCreatedAt(OffsetDateTime.now());
		inboxRepo.save(row);

		rule.setLastDispatchedAt(OffsetDateTime.now());
		patrolRepo.save(rule);

		log.info("dispatched rule={} → user={} inbox_id={} channel=in_app",
				rule.getId(), rule.getCreatedBy(), row.getId());
	}

	private String defaultBody(Map<String, Object> runOutput) {
		if (runOutput == null || runOutput.isEmpty()) return "Rule completed.";
		Object summary = runOutput.get("result_summary");
		return summary != null ? summary.toString() : "Rule completed — open the run for details.";
	}

	/** Replace {key} occurrences with stringified runOutput[key]. */
	private String renderTemplate(String template, Map<String, Object> runOutput) {
		if (runOutput == null) return template;
		String out = template;
		for (Map.Entry<String, Object> e : runOutput.entrySet()) {
			String placeholder = "{" + e.getKey() + "}";
			Object value = e.getValue();
			out = out.replace(placeholder, value == null ? "" : value.toString());
		}
		return out;
	}
}
