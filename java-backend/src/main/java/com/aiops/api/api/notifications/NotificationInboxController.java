package com.aiops.api.api.notifications;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.auth.Authorities;
import com.aiops.api.common.ApiException;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.notification.NotificationInboxEntity;
import com.aiops.api.domain.notification.NotificationInboxRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.PageRequest;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * Phase 9 — bell-icon polls this endpoint every ~30s. The unread query
 * uses a partial index keyed on (user_id, created_at desc) WHERE read_at
 * IS NULL so latency is constant regardless of historical inbox size.
 */
@RestController
@RequestMapping("/api/v1/notifications")
@RequiredArgsConstructor
public class NotificationInboxController {

	private final NotificationInboxRepository repo;

	/** Bell-icon poll: unread + recent N for current user. */
	@GetMapping("/inbox")
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<InboxResponse> inbox(@RequestParam(defaultValue = "false") boolean unreadOnly,
	                                        @RequestParam(defaultValue = "50") int limit,
	                                        @AuthenticationPrincipal AuthPrincipal caller) {
		Long uid = caller.userId();
		long unreadCount = repo.countByUserIdAndReadAtIsNull(uid);
		List<NotificationInboxEntity> rows = unreadOnly
				? repo.findUnreadByUser(uid)
				: repo.findRecentByUser(uid, PageRequest.of(0, Math.max(1, Math.min(limit, 200))));
		return ApiResponse.ok(new InboxResponse(
				unreadCount,
				rows.stream().map(NotificationInboxController::dtoOf).toList()
		));
	}

	@PostMapping("/{id}/read")
	@Transactional
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Void> markRead(@PathVariable Long id,
	                                  @AuthenticationPrincipal AuthPrincipal caller) {
		NotificationInboxEntity row = repo.findById(id).orElseThrow(() -> ApiException.notFound("notification"));
		if (!row.getUserId().equals(caller.userId())) {
			throw ApiException.forbidden("not your notification");
		}
		if (row.getReadAt() == null) {
			row.setReadAt(OffsetDateTime.now());
			repo.save(row);
		}
		return ApiResponse.ok(null);
	}

	@PostMapping("/read-all")
	@Transactional
	@PreAuthorize(Authorities.ANY_ROLE)
	public ApiResponse<Long> markAllRead(@AuthenticationPrincipal AuthPrincipal caller) {
		Long uid = caller.userId();
		List<NotificationInboxEntity> unread = repo.findUnreadByUser(uid);
		OffsetDateTime now = OffsetDateTime.now();
		unread.forEach(n -> n.setReadAt(now));
		repo.saveAll(unread);
		return ApiResponse.ok((long) unread.size());
	}

	public record InboxResponse(long unreadCount, List<InboxItem> items) {}

	public record InboxItem(Long id, Long ruleId, String payload,
	                        OffsetDateTime readAt, OffsetDateTime createdAt) {}

	private static InboxItem dtoOf(NotificationInboxEntity e) {
		return new InboxItem(e.getId(), e.getRuleId(), e.getPayload(),
				e.getReadAt(), e.getCreatedAt());
	}
}
