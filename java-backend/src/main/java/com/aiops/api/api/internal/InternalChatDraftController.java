package com.aiops.api.api.internal;

import com.aiops.api.api.chatdraft.ChatDraftService;
import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * Coordinator 草稿能力 (2026-07-12) — sidecar 讀 Chat 草稿暫存區。
 * user 曾對 agent 說「列草稿」但 agent 只看得到 skills_v2 的 draft，
 * 跟左欄 My Drafts（本表）數量對不上。讀-only；刪除等操作走對話內
 * 草稿卡（browser 端使用者確認）。
 */
@RestController
@RequestMapping("/internal/chat-drafts")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalChatDraftController {

	private final ChatDraftService service;

	public InternalChatDraftController(ChatDraftService service) {
		this.service = service;
	}

	@GetMapping
	public ApiResponse<Map<String, Object>> list(@RequestParam("user_id") Long userId) {
		return ApiResponse.ok(service.list(userId));
	}

	@GetMapping("/{id}")
	public ApiResponse<Map<String, Object>> get(@PathVariable Long id,
	                                            @RequestParam("user_id") Long userId) {
		return ApiResponse.ok(service.get(id, userId));
	}
}
