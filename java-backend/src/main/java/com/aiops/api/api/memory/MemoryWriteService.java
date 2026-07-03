package com.aiops.api.api.memory;

import com.aiops.api.common.ApiException;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeEntity;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeRepository;
import com.aiops.api.domain.agentknowledge.BlockDocMemoEntity;
import com.aiops.api.domain.agentknowledge.BlockDocMemoRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Map;
import java.util.Set;

/**
 * Memory-layer write path (V70; spec MULTI_AGENT_MEMORY_SPEC §3.2, W1-W3).
 *
 * <p>Two sinks, one philosophy:
 * <ul>
 *   <li>agent_knowledge — Planner/Repair fast-path memories (preference /
 *       presentation / correction). Written active=true (E2: effective
 *       immediately; Supervisor prunes later). Embedding stays NULL — the
 *       30s backfill job picks it up, after which the EXISTING RAG pipeline
 *       recalls the row with zero new read-side code.</li>
 *   <li>block_doc_memos — Builder's doc sticky-notes: review queue only,
 *       never mutates block_docs directly.</li>
 * </ul>
 *
 * <p>Dedup lives HERE (server-side, survives sidecar restarts): knowledge by
 * (user, memo_class, title); doc memos by (block, param, episode). Flood caps
 * are enforced sidecar-side per build (E4).
 */
@Service
public class MemoryWriteService {

    private static final Set<String> CLASSES = Set.of(
            "domain", "preference", "presentation", "correction", "episodic", "procedure");
    private static final Set<String> APPLIES = Set.of("plan", "execute", "both");
    private static final Set<String> WRITERS = Set.of("planner", "builder", "repair", "human");

    private final AgentKnowledgeRepository knowledge;
    private final BlockDocMemoRepository memos;

    public MemoryWriteService(AgentKnowledgeRepository knowledge, BlockDocMemoRepository memos) {
        this.knowledge = knowledge;
        this.memos = memos;
    }

    /** Create one agent-written knowledge row; dedup by (user, class, title).
     *
     * <p>{@code active}: preference/presentation (user-explicit signals) go
     * live immediately; corrections land as INACTIVE drafts — the 2026-07-03
     * pollution experiment (0/3 -> 3/3 after deactivation) showed failure-notes
     * recalled at the execute layer mislead similar builds. Supervisor (Phase 5)
     * reviews + promotes drafts. */
    @Transactional
    public Map<String, Object> createKnowledge(Long userId, String memoClass, String title,
                                               String body, String appliesTo, String source,
                                               Boolean active, String writtenBy) {
        if (userId == null) throw ApiException.badRequest("user_id required");
        if (memoClass == null || !CLASSES.contains(memoClass)) {
            throw ApiException.badRequest("memo_class must be one of " + CLASSES);
        }
        if (title == null || title.isBlank() || body == null || body.isBlank()) {
            throw ApiException.badRequest("title and body required");
        }
        var existing = knowledge.findFirstByUserIdAndMemoClassAndTitle(userId, memoClass, title);
        if (existing.isPresent()) {
            return Map.of("id", existing.get().getId(), "deduped", true);
        }
        AgentKnowledgeEntity e = new AgentKnowledgeEntity();
        e.setUserId(userId);
        e.setScopeType("global");           // per-user isolation is the user_id filter (Q3)
        e.setTitle(title.length() > 200 ? title.substring(0, 200) : title);
        e.setBody(body);
        e.setPriority("med");
        e.setAppliesTo(appliesTo != null && APPLIES.contains(appliesTo) ? appliesTo : "both");
        e.setMemoClass(memoClass);
        // V71 provenance: unknown/invalid → NULL (honest "unclassified") rather
        // than a guessed default. Callers (W1/W3) pass planner/repair explicitly.
        e.setWrittenBy(writtenBy != null && WRITERS.contains(writtenBy) ? writtenBy : null);
        e.setActive(active == null || active);  // E2-revised: caller decides; default live
        e.setSource(source == null || source.isBlank() ? "agent_fast" : source);
        e = knowledge.save(e);              // embedding NULL → 30s backfill job embeds it
        return Map.of("id", e.getId(), "deduped", false);
    }

    /** Create one pending doc memo; dedup by (block, param, episode). */
    @Transactional
    public Map<String, Object> createDocMemo(String blockId, String param, String memo,
                                             String verdictContext, String fromEpisode) {
        if (blockId == null || blockId.isBlank() || memo == null || memo.isBlank()) {
            throw ApiException.badRequest("block_id and memo required");
        }
        if (memos.existsByBlockIdAndParamAndFromEpisode(blockId, param, fromEpisode)) {
            return Map.of("deduped", true);
        }
        BlockDocMemoEntity m = new BlockDocMemoEntity();
        m.setBlockId(blockId);
        m.setParam(param);
        m.setMemo(memo);
        m.setVerdictContext(verdictContext);
        m.setFromEpisode(fromEpisode);
        m = memos.save(m);
        return Map.of("id", m.getId(), "deduped", false);
    }
}
