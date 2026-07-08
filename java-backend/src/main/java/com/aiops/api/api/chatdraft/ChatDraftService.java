package com.aiops.api.api.chatdraft;

import com.aiops.api.common.ApiException;
import com.aiops.api.common.JsonUtils;
import com.aiops.api.domain.chatdraft.ChatDraftEntity;
import com.aiops.api.domain.chatdraft.ChatDraftRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Chat 草稿暫存區 service (V78). Owns the ring-buffer eviction + JSON serdes;
 * the controller stays thin (bind + delegate).
 *
 * <p>Eviction contract: at most {@link #MAX_DRAFTS} per user. On insert, if
 * over the cap, drop the OLDEST {@code marked=false} drafts until back at cap.
 * Marked drafts are never auto-evicted (a user with 10 marked can exceed the
 * cap — the UI's limit warning is the signal, not silent deletion).
 */
@Service
public class ChatDraftService {

    /** User decision 2026-07-08: keep the most-recent 10. */
    public static final int MAX_DRAFTS = 10;

    private final ChatDraftRepository repo;
    private final ObjectMapper mapper;

    public ChatDraftService(ChatDraftRepository repo, ObjectMapper mapper) {
        this.repo = repo;
        this.mapper = mapper;
    }

    /** Shelf list — light projection (no heavy pipeline_json / columns blobs).
     *  Plus a header summary the UI needs for the capacity gauge + warning. */
    public Map<String, Object> list(Long userId) {
        List<ChatDraftEntity> rows = repo.findByUserIdOrderByCreatedAtDesc(userId);
        List<Map<String, Object>> items = new ArrayList<>(rows.size());
        int marked = 0;
        for (ChatDraftEntity d : rows) {
            if (Boolean.TRUE.equals(d.getMarked())) marked++;
            items.add(summary(d));
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("drafts", items);
        out.put("used", rows.size());
        out.put("marked", marked);
        out.put("limit", MAX_DRAFTS);
        // free slots the UI turns into the "還剩 N 位" limit warning
        out.put("free", Math.max(0, MAX_DRAFTS - rows.size()));
        return out;
    }

    /** Full draft incl. pipeline_json + columns — for open / enable. */
    public Map<String, Object> get(Long id, Long userId) {
        ChatDraftEntity d = repo.findByIdAndUserId(id, userId)
                .orElseThrow(() -> ApiException.notFound("chat draft"));
        Map<String, Object> m = summary(d);
        m.put("pipeline_json", JsonUtils.parseObject(mapper, d.getPipelineJson()));
        m.put("columns", JsonUtils.parseObject(mapper, d.getColumnsJson()));
        return m;
    }

    @Transactional
    public Map<String, Object> create(Long userId, Map<String, Object> body) {
        Object pj = body.get("pipeline_json");
        if (!(pj instanceof Map)) {
            throw ApiException.badRequest("pipeline_json is required");
        }
        ChatDraftEntity d = new ChatDraftEntity();
        d.setUserId(userId);
        d.setName(str(body.get("name")));
        d.setNl(str(body.get("nl")));
        d.setPipelineJson(JsonUtils.safeWrite(mapper, pj));
        d.setColumnsJson(JsonUtils.safeWrite(mapper,
                body.get("columns") instanceof Map ? body.get("columns") : Map.of()));
        d.setKind(str(body.get("kind")));
        d.setNodeCount(intOf(body.get("node_count")));
        d.setEdgeCount(intOf(body.get("edge_count")));
        ChatDraftEntity saved = repo.save(d);
        evict(userId);
        return summary(saved);
    }

    @Transactional
    public Map<String, Object> setMark(Long id, Long userId, boolean marked) {
        ChatDraftEntity d = repo.findByIdAndUserId(id, userId)
                .orElseThrow(() -> ApiException.notFound("chat draft"));
        d.setMarked(marked);
        return summary(repo.save(d));
    }

    @Transactional
    public void delete(Long id, Long userId) {
        ChatDraftEntity d = repo.findByIdAndUserId(id, userId)
                .orElseThrow(() -> ApiException.notFound("chat draft"));
        repo.delete(d);
    }

    /** keepMarked=true → 清除未標記（保留已標記）; false → 清空全部。 */
    @Transactional
    public Map<String, Object> clear(Long userId, boolean keepMarked) {
        int removed = keepMarked ? repo.deleteUnmarked(userId) : repo.deleteAllForUser(userId);
        return Map.of("removed", removed);
    }

    // ── eviction: drop oldest unmarked until at/under the cap ───────────
    private void evict(Long userId) {
        long count = repo.countByUserId(userId);
        if (count <= MAX_DRAFTS) return;
        List<ChatDraftEntity> unmarkedOldestFirst =
                repo.findByUserIdAndMarkedFalseOrderByCreatedAtAsc(userId);
        int toDrop = (int) (count - MAX_DRAFTS);
        for (ChatDraftEntity d : unmarkedOldestFirst) {
            if (toDrop <= 0) break;
            repo.delete(d);
            toDrop--;
        }
        // If toDrop still > 0, the user has > MAX marked drafts — protected by
        // design; the UI's capacity gauge surfaces the over-limit state.
    }

    // ── helpers ────────────────────────────────────────────────────────
    private Map<String, Object> summary(ChatDraftEntity d) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", d.getId());
        m.put("name", d.getName());
        m.put("nl", d.getNl());
        m.put("kind", d.getKind());
        m.put("node_count", d.getNodeCount());
        m.put("edge_count", d.getEdgeCount());
        m.put("marked", Boolean.TRUE.equals(d.getMarked()));
        m.put("created_at", d.getCreatedAt() == null ? null : d.getCreatedAt().toString());
        return m;
    }

    private static String str(Object o) {
        return o == null ? "" : String.valueOf(o);
    }

    private static int intOf(Object o) {
        if (o instanceof Number n) return n.intValue();
        try {
            return o == null ? 0 : Integer.parseInt(String.valueOf(o));
        } catch (NumberFormatException e) {
            return 0;
        }
    }
}
