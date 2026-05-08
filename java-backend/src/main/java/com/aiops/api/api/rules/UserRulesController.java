package com.aiops.api.api.rules;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.patrol.AutoPatrolEntity;
import com.aiops.api.domain.patrol.AutoPatrolRepository;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import jakarta.validation.constraints.NotBlank;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Set;

/**
 * Phase 9 — User-owned personal rules. Each authenticated user can list /
 * create / pause / delete their own rules; cannot see or touch others'.
 *
 * Wraps the same auto_patrols table as the existing alarm-generating
 * AutoPatrolController, but filtered + auth-checked to the caller's own
 * created_by + restricted to non-shared_alarm kinds.
 */
@RestController
@RequestMapping("/api/v1/rules")
@RequiredArgsConstructor
public class UserRulesController {

	private static final Set<String> ALLOWED_KINDS = Set.of(
			"personal_briefing", "weekly_report", "saved_query", "watch_rule"
	);

	private final AutoPatrolRepository ruleRepo;
	private final PipelineRepository pipelineRepo;

	@GetMapping
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<List<Dtos.RuleDto>> list(@AuthenticationPrincipal AuthPrincipal caller) {
		List<AutoPatrolEntity> mine = ruleRepo.findByCreatedByAndKindNot(
				caller.userId(), "shared_alarm");
		return ApiResponse.ok(mine.stream().map(Dtos::ruleOf).toList());
	}

	@GetMapping("/{id}")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Dtos.RuleDto> get(@PathVariable Long id,
	                                     @AuthenticationPrincipal AuthPrincipal caller) {
		AutoPatrolEntity e = ruleRepo.findById(id).orElseThrow(() -> ApiException.notFound("rule"));
		ensureOwnedBy(e, caller);
		return ApiResponse.ok(Dtos.ruleOf(e));
	}

	@PostMapping
	@Transactional
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Dtos.RuleDto> create(@RequestBody Dtos.CreateRuleRequest req,
	                                        @AuthenticationPrincipal AuthPrincipal caller) {
		if (req.name() == null || req.name().isBlank()) {
			throw ApiException.badRequest("name required");
		}
		if (req.kind() == null || !ALLOWED_KINDS.contains(req.kind())) {
			throw ApiException.badRequest("kind must be one of " + ALLOWED_KINDS);
		}
		if (req.scheduleCron() == null || req.scheduleCron().isBlank()) {
			throw ApiException.badRequest("schedule_cron required");
		}

		// Resolve pipeline: either client provides pipeline_id or pipeline_json
		// (in which case we materialise a new pb_pipelines row).
		Long pipelineId;
		if (req.pipelineId() != null) {
			pipelineId = req.pipelineId();
			PipelineEntity p = pipelineRepo.findById(pipelineId)
					.orElseThrow(() -> ApiException.notFound("pipeline"));
			// access check: caller must own the pipeline OR it's a published one
			if (p.getCreatedBy() != null && !p.getCreatedBy().equals(caller.userId())
					&& !"active".equals(p.getStatus())) {
				throw ApiException.forbidden("cannot bind to another user's draft pipeline");
			}
		} else if (req.pipelineJson() != null && !req.pipelineJson().isBlank()) {
			PipelineEntity p = new PipelineEntity();
			p.setName(req.name() + " (rule)");
			p.setDescription("Auto-created for personal rule via /api/v1/rules");
			p.setStatus("active");           // skip draft → active for rule pipelines
			p.setPipelineKind("auto_patrol");
			p.setPipelineJson(req.pipelineJson());
			p.setCreatedBy(caller.userId());
			p = pipelineRepo.save(p);
			pipelineId = p.getId();
		} else {
			throw ApiException.badRequest("either pipeline_id or pipeline_json required");
		}

		AutoPatrolEntity rule = new AutoPatrolEntity();
		rule.setName(req.name());
		rule.setDescription(req.description() == null ? "" : req.description());
		rule.setKind(req.kind());
		rule.setTriggerMode("schedule");
		rule.setCronExpr(req.scheduleCron());
		rule.setPipelineId(pipelineId);
		rule.setCreatedBy(caller.userId());
		rule.setIsActive(Boolean.TRUE);
		rule.setNotificationChannels(req.notificationChannels() == null
				? "[{\"type\":\"in_app\"}]" : req.notificationChannels());
		rule.setNotificationTemplate(req.notificationTemplate());
		// Personal rules don't generate alarms, so leave alarm_severity / title null.
		// target_scope unused for personal rules; keep default JSON literal so
		// the NOT NULL column is satisfied.
		rule = ruleRepo.save(rule);

		return ApiResponse.ok(Dtos.ruleOf(rule));
	}

	@PatchMapping("/{id}")
	@Transactional
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Dtos.RuleDto> patch(@PathVariable Long id,
	                                       @RequestBody Dtos.PatchRuleRequest req,
	                                       @AuthenticationPrincipal AuthPrincipal caller) {
		AutoPatrolEntity e = ruleRepo.findById(id).orElseThrow(() -> ApiException.notFound("rule"));
		ensureOwnedBy(e, caller);
		if (req.isActive() != null) e.setIsActive(req.isActive());
		if (req.scheduleCron() != null) e.setCronExpr(req.scheduleCron());
		if (req.notificationTemplate() != null) e.setNotificationTemplate(req.notificationTemplate());
		if (req.notificationChannels() != null) e.setNotificationChannels(req.notificationChannels());
		ruleRepo.save(e);
		return ApiResponse.ok(Dtos.ruleOf(e));
	}

	@DeleteMapping("/{id}")
	@Transactional
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Void> delete(@PathVariable Long id,
	                                @AuthenticationPrincipal AuthPrincipal caller) {
		AutoPatrolEntity e = ruleRepo.findById(id).orElseThrow(() -> ApiException.notFound("rule"));
		ensureOwnedBy(e, caller);
		ruleRepo.delete(e);
		return ApiResponse.ok(null);
	}

	private void ensureOwnedBy(AutoPatrolEntity e, AuthPrincipal caller) {
		if (e.getCreatedBy() == null || !e.getCreatedBy().equals(caller.userId())) {
			throw ApiException.forbidden("not your rule");
		}
		if ("shared_alarm".equals(e.getKind())) {
			throw ApiException.forbidden("shared alarms managed via /api/v1/auto-patrols");
		}
	}
}
