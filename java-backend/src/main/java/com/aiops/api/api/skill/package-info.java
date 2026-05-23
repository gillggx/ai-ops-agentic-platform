/**
 * Skill Document HTTP layer + business services.
 *
 * <p>Layering (Phase 12 OOP refactor 2026-05-23):
 * <ul>
 *   <li>{@link com.aiops.api.api.skill.SkillDocumentController} — thin HTTP:
 *       parameter binding, {@code @PreAuthorize}, DTO mapping, SSE wiring.</li>
 *   <li>{@link com.aiops.api.api.skill.SkillDocumentService} — CRUD + slug
 *       auto-gen + stage auto-flip + materializer side effects on status
 *       transitions; sidecar coordination for confirm-check / steps.</li>
 *   <li>{@link com.aiops.api.api.skill.SkillRunnerService} — orchestrator
 *       for the SSE run flow; iterates steps, fires confirm gate, emits
 *       {@code RunEvent} stream.</li>
 *   <li>{@link com.aiops.api.api.skill.SkillStepExecutor} — runs a single
 *       step's pipeline through the Python sidecar; parses
 *       {@code block_step_check} verdict + data_view previews.</li>
 *   <li>{@link com.aiops.api.api.skill.SkillAlarmEmitter} — writes
 *       {@code alarms} row when a patrol step triggers; counters + dedup
 *       + ExecutionLog cascade + scheduler dispatchAlarm fan-out.</li>
 *   <li>{@link com.aiops.api.api.skill.SkillMaterializeService} —
 *       publish/unpublish writes / clears {@code auto_patrols} +
 *       {@code pipeline_auto_check_triggers} rows on stable transition.</li>
 * </ul>
 *
 * <p>Repository access lives in {@code com.aiops.api.domain.skill.*}; the
 * service tier is the only thing that touches it directly.
 */
package com.aiops.api.api.skill;
