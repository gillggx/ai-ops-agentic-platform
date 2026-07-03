package com.aiops.api.api.supervisor;

import com.aiops.api.common.ApiException;
import com.aiops.api.common.JsonUtils;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeEntity;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeRepository;
import com.aiops.api.domain.agentknowledge.BlockDocMemoEntity;
import com.aiops.api.domain.agentknowledge.BlockDocMemoRepository;
import com.aiops.api.domain.supervisor.SupervisorActionEntity;
import com.aiops.api.domain.supervisor.SupervisorActionRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.*;

/**
 * Supervisor curation (Phase 5, V72) — the memory layer's WRITE-BACK brain.
 *
 * <p>Flow: sidecar proposer (Haiku, offline) POSTs proposals → they queue here
 * as status=proposed → a human reviews in /supervisor → approve() commits the
 * per-type mutation, reject() just stamps the audit row. The Supervisor NEVER
 * writes memories without an approval (2026-07-03 pollution incident).
 *
 * <p>Proposal shapes (JSON in {@code proposal}):
 * <ul>
 *   <li>MERGE   — {keep_id, remove_ids[], merged_body?} : dedup near-identical
 *       preference/presentation rows; losers go inactive, keeper optionally
 *       gets the merged body.</li>
 *   <li>CORRECT — {target_id, new_title?, new_body, promote} : rewrite a draft
 *       correction into a clean durable note; promote=true also activates.</li>
 *   <li>PRUNE   — {target_ids[]} : stale / user-rejected rows → inactive.</li>
 *   <li>PROMOTE — {memo_class: domain|procedure, title, body, applies_to} :
 *       distil a cross-build pattern into a NEW durable row
 *       (written_by=supervisor, source=supervisor, active).</li>
 *   <li>DOC_REVISE — {block_id, memo_ids[], revised_doc_draft} : marks the
 *       doc memos promoted and keeps the draft on the action row —
 *       block_docs itself is NOT touched (single source of truth).</li>
 * </ul>
 */
@Service
public class SupervisorCurationService {

    private static final Set<String> TYPES =
            Set.of("MERGE", "CORRECT", "PRUNE", "PROMOTE", "DOC_REVISE");
    private static final Set<String> PROMOTE_CLASSES = Set.of("domain", "procedure");

    private final SupervisorActionRepository actions;
    private final AgentKnowledgeRepository knowledge;
    private final BlockDocMemoRepository docMemos;
    private final ObjectMapper mapper;

    public SupervisorCurationService(SupervisorActionRepository actions,
                                     AgentKnowledgeRepository knowledge,
                                     BlockDocMemoRepository docMemos,
                                     ObjectMapper mapper) {
        this.actions = actions;
        this.knowledge = knowledge;
        this.docMemos = docMemos;
        this.mapper = mapper;
    }

    // ── propose (sidecar) ───────────────────────────────────────────────

    @Transactional
    public Map<String, Object> propose(String actionType, List<?> targetIds,
                                       Map<String, Object> proposal, String rationale,
                                       Map<String, Object> proposerMeta) {
        if (actionType == null || !TYPES.contains(actionType)) {
            throw ApiException.badRequest("action_type must be one of " + TYPES);
        }
        if (proposal == null || proposal.isEmpty()) {
            throw ApiException.badRequest("proposal required");
        }
        String targets = JsonUtils.safeWrite(mapper, targetIds == null ? List.of() : targetIds);
        if (actions.existsByActionTypeAndTargetIdsAndStatus(actionType, targets, "proposed")) {
            return Map.of("deduped", true);
        }
        SupervisorActionEntity a = new SupervisorActionEntity();
        a.setActionType(actionType);
        a.setTargetIds(targets);
        a.setProposal(JsonUtils.safeWrite(mapper, proposal));
        a.setRationale(rationale);
        a.setProposerMeta(JsonUtils.safeWrite(mapper, proposerMeta));
        a = actions.save(a);
        return Map.of("id", a.getId(), "deduped", false);
    }

    // ── list / review (user-facing) ─────────────────────────────────────

    @Transactional(readOnly = true)
    public List<Map<String, Object>> list(String status) {
        List<SupervisorActionEntity> rows = (status == null || status.isBlank())
                ? actions.findTop200ByOrderByIdDesc()
                : actions.findTop200ByStatusOrderByIdDesc(status);
        List<Map<String, Object>> out = new ArrayList<>();
        for (SupervisorActionEntity a : rows) out.add(toDto(a));
        return out;
    }

    @Transactional(readOnly = true)
    public Map<String, Object> counts() {
        return Map.of(
                "proposed", actions.countByStatus("proposed"),
                "approved", actions.countByStatus("approved"),
                "rejected", actions.countByStatus("rejected"));
    }

    /** Human approval — commits the per-type mutation atomically with the
     *  status flip. Throws (rolling back everything) if the commit fails. */
    @Transactional
    public Map<String, Object> approve(Long id, Long reviewerId) {
        SupervisorActionEntity a = actions.findById(id)
                .orElseThrow(() -> ApiException.notFound("proposal " + id));
        if (!"proposed".equals(a.getStatus())) {
            throw ApiException.badRequest("proposal " + id + " already " + a.getStatus());
        }
        Map<String, Object> p = JsonUtils.parseObject(mapper, a.getProposal());
        Map<String, Object> result = switch (a.getActionType()) {
            case "MERGE" -> commitMerge(p);
            case "CORRECT" -> commitCorrect(p);
            case "PRUNE" -> commitPrune(p);
            case "PROMOTE" -> commitPromote(p);
            case "DOC_REVISE" -> commitDocRevise(p, reviewerId);
            default -> throw ApiException.badRequest("unknown action_type " + a.getActionType());
        };
        a.setStatus("approved");
        a.setReviewedBy(reviewerId);
        a.setReviewedAt(OffsetDateTime.now());
        a.setCommitResult(JsonUtils.safeWrite(mapper, result));
        actions.save(a);
        return toDto(a);
    }

    @Transactional
    public Map<String, Object> reject(Long id, Long reviewerId) {
        SupervisorActionEntity a = actions.findById(id)
                .orElseThrow(() -> ApiException.notFound("proposal " + id));
        if (!"proposed".equals(a.getStatus())) {
            throw ApiException.badRequest("proposal " + id + " already " + a.getStatus());
        }
        a.setStatus("rejected");
        a.setReviewedBy(reviewerId);
        a.setReviewedAt(OffsetDateTime.now());
        actions.save(a);
        return toDto(a);
    }

    // ── per-type commits ────────────────────────────────────────────────

    private Map<String, Object> commitMerge(Map<String, Object> p) {
        Long keepId = asLong(p.get("keep_id"));
        List<Long> removeIds = asLongList(p.get("remove_ids"));
        if (keepId == null || removeIds.isEmpty()) {
            throw ApiException.badRequest("MERGE needs keep_id + remove_ids");
        }
        AgentKnowledgeEntity keep = knowledge.findById(keepId)
                .orElseThrow(() -> ApiException.notFound("knowledge " + keepId));
        Object mergedBody = p.get("merged_body");
        if (mergedBody instanceof String s && !s.isBlank()) {
            keep.setBody(s);
            knowledge.save(keep);
        }
        int deactivated = 0;
        for (Long rid : removeIds) {
            if (rid.equals(keepId)) continue;   // never deactivate the keeper
            Optional<AgentKnowledgeEntity> r = knowledge.findById(rid);
            if (r.isPresent()) {
                r.get().setActive(false);
                knowledge.save(r.get());
                deactivated++;
            }
        }
        return Map.of("kept", keepId, "deactivated", deactivated);
    }

    private Map<String, Object> commitCorrect(Map<String, Object> p) {
        Long targetId = asLong(p.get("target_id"));
        Object newBody = p.get("new_body");
        if (targetId == null || !(newBody instanceof String nb) || nb.isBlank()) {
            throw ApiException.badRequest("CORRECT needs target_id + new_body");
        }
        AgentKnowledgeEntity e = knowledge.findById(targetId)
                .orElseThrow(() -> ApiException.notFound("knowledge " + targetId));
        if (p.get("new_title") instanceof String nt && !nt.isBlank()) {
            e.setTitle(nt.length() > 200 ? nt.substring(0, 200) : nt);
        }
        e.setBody(nb);
        boolean promote = Boolean.TRUE.equals(p.get("promote"))
                || "true".equals(String.valueOf(p.get("promote")));
        e.setActive(promote);
        knowledge.save(e);
        return Map.of("corrected", targetId, "activated", promote);
    }

    private Map<String, Object> commitPrune(Map<String, Object> p) {
        List<Long> ids = asLongList(p.get("target_ids"));
        if (ids.isEmpty()) throw ApiException.badRequest("PRUNE needs target_ids");
        int pruned = 0;
        for (Long rid : ids) {
            Optional<AgentKnowledgeEntity> r = knowledge.findById(rid);
            if (r.isPresent() && Boolean.TRUE.equals(r.get().getActive())) {
                r.get().setActive(false);
                knowledge.save(r.get());
                pruned++;
            }
        }
        return Map.of("pruned", pruned);
    }

    private Map<String, Object> commitPromote(Map<String, Object> p) {
        String memoClass = String.valueOf(p.get("memo_class"));
        Object title = p.get("title");
        Object body = p.get("body");
        if (!PROMOTE_CLASSES.contains(memoClass)) {
            throw ApiException.badRequest("PROMOTE memo_class must be one of " + PROMOTE_CLASSES);
        }
        if (!(title instanceof String t) || t.isBlank()
                || !(body instanceof String b) || b.isBlank()) {
            throw ApiException.badRequest("PROMOTE needs title + body");
        }
        Long userId = asLong(p.get("user_id"));
        AgentKnowledgeEntity e = new AgentKnowledgeEntity();
        e.setUserId(userId == null ? 1L : userId);   // matches read-path default
        e.setScopeType("global");
        e.setTitle(t.length() > 200 ? t.substring(0, 200) : t);
        e.setBody(b);
        e.setPriority("med");
        String applies = String.valueOf(p.get("applies_to"));
        e.setAppliesTo(Set.of("plan", "execute", "both").contains(applies) ? applies : "both");
        e.setMemoClass(memoClass);
        e.setWrittenBy("supervisor");
        e.setSource("supervisor");
        e.setActive(true);   // human just approved — live immediately
        e = knowledge.save(e);   // embedding NULL → 30s backfill embeds it
        return Map.of("created", e.getId(), "memo_class", memoClass);
    }

    private Map<String, Object> commitDocRevise(Map<String, Object> p, Long reviewerId) {
        List<Long> memoIds = asLongList(p.get("memo_ids"));
        if (memoIds.isEmpty()) throw ApiException.badRequest("DOC_REVISE needs memo_ids");
        // The revised_doc_draft stays on the action row (commit_result / proposal).
        // block_docs is NOT mutated here — the draft is handed to the block-doc
        // editor flow separately (single source of truth preserved).
        int promoted = 0;
        for (Long mid : memoIds) {
            Optional<BlockDocMemoEntity> m = docMemos.findById(mid);
            if (m.isPresent() && "pending".equals(m.get().getStatus())) {
                m.get().setStatus("promoted");
                m.get().setReviewedBy(reviewerId);
                m.get().setReviewedAt(OffsetDateTime.now());
                docMemos.save(m.get());
                promoted++;
            }
        }
        return Map.of("memos_promoted", promoted,
                "draft_kept_on_action", p.get("revised_doc_draft") != null);
    }

    // ── helpers ─────────────────────────────────────────────────────────

    private Map<String, Object> toDto(SupervisorActionEntity a) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", a.getId());
        m.put("action_type", a.getActionType());
        m.put("target_ids", JsonUtils.parseListOfObjects(mapper, a.getTargetIds()));
        m.put("proposal", JsonUtils.parseObject(mapper, a.getProposal()));
        m.put("rationale", a.getRationale());
        m.put("status", a.getStatus());
        m.put("proposer_meta", JsonUtils.parseObject(mapper, a.getProposerMeta()));
        m.put("created_at", a.getCreatedAt() == null ? null : a.getCreatedAt().toString());
        m.put("reviewed_by", a.getReviewedBy());
        m.put("reviewed_at", a.getReviewedAt() == null ? null : a.getReviewedAt().toString());
        m.put("commit_result", JsonUtils.parseObject(mapper, a.getCommitResult()));
        return m;
    }

    private static Long asLong(Object o) {
        if (o == null) return null;
        if (o instanceof Number n) return n.longValue();
        try {
            return Long.parseLong(String.valueOf(o));
        } catch (NumberFormatException ex) {
            return null;
        }
    }

    private static List<Long> asLongList(Object o) {
        List<Long> out = new ArrayList<>();
        if (o instanceof List<?> l) {
            for (Object x : l) {
                Long v = asLong(x);
                if (v != null) out.add(v);
            }
        }
        return out;
    }
}
