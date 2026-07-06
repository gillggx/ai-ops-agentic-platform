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
    /** V75: sidecar may only mint these directly — stale/archived are
     *  lifecycle outcomes, never a birth state. */
    private static final Set<String> STATUS_WHITELIST = Set.of("draft", "active");
    private static final Set<String> SUBJECT_KINDS = Set.of(
            "block", "tool", "skill", "request_class", "general");
    private static final int MAX_SUBJECT_ID_LEN = 80;

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
        return createKnowledge(userId, memoClass, title, body, appliesTo, source,
                active, writtenBy, null, null, null);
    }

    /** V75 governance overload — optional lifecycle {@code status} (whitelist
     *  draft/active) + subject index. Status resolution when the body omits it:
     *  active=false rows written by repair for a correction are W3 drafts
     *  (status='draft'); any other active=false is an archive; live rows are
     *  'active'. */
    @Transactional
    public Map<String, Object> createKnowledge(Long userId, String memoClass, String title,
                                               String body, String appliesTo, String source,
                                               Boolean active, String writtenBy,
                                               String status, String subjectKind, String subjectId) {
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
        String effectiveWrittenBy = writtenBy != null && WRITERS.contains(writtenBy) ? writtenBy : null;
        e.setWrittenBy(effectiveWrittenBy);
        boolean live = active == null || active;
        e.setActive(live);                      // E2-revised: caller decides; default live
        // V75 lifecycle status. Explicit body value wins (whitelisted);
        // otherwise derive from active: repair-correction inactive rows are
        // the W3 draft convention, any other inactive row is an archive.
        if (status != null && STATUS_WHITELIST.contains(status)) {
            e.setStatus(status);
        } else if (!live) {
            boolean repairCorrectionDraft = "repair".equals(effectiveWrittenBy)
                    && "correction".equals(memoClass);
            e.setStatus(repairCorrectionDraft ? "draft" : "archived");
        } else {
            e.setStatus("active");
        }
        // V75 subject index — whitelist protects the DB CHECK constraint;
        // subject_id only makes sense alongside a valid kind.
        if (subjectKind != null && SUBJECT_KINDS.contains(subjectKind)) {
            e.setSubjectKind(subjectKind);
            if (subjectId != null && !subjectId.isBlank()) {
                e.setSubjectId(subjectId.length() > MAX_SUBJECT_ID_LEN
                        ? subjectId.substring(0, MAX_SUBJECT_ID_LEN) : subjectId);
            }
        }
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
