package com.aiops.api.api.supervisor;

import com.aiops.api.common.ApiException;
import com.aiops.api.common.JsonUtils;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeEntity;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeRepository;
import com.aiops.api.domain.agentknowledge.BlockDocMemoEntity;
import com.aiops.api.domain.agentknowledge.BlockDocMemoRepository;
import com.aiops.api.domain.blockdoc.BlockDocEntity;
import com.aiops.api.domain.blockdoc.BlockDocRepository;
import com.aiops.api.domain.supervisor.SupervisorActionEntity;
import com.aiops.api.domain.supervisor.SupervisorActionRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

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
 *   <li>CFG / ISSUE (W3) — free-form proposal JSON, stored as-is with no
 *       target validation: config-change and issue-tracker suggestions that
 *       a human lands OUTSIDE this system. Approving one commits nothing —
 *       landed_at stays NULL until the manual landing is recorded.</li>
 * </ul>
 */
@Service
public class SupervisorCurationService {

    private static final Logger log = LoggerFactory.getLogger(SupervisorCurationService.class);

    private static final Set<String> TYPES =
            Set.of("MERGE", "CORRECT", "PRUNE", "PROMOTE", "DOC_REVISE", "CFG", "ISSUE");
    /** W3: approve() flips status only — the change lands manually, later. */
    private static final Set<String> MANUAL_LANDING_TYPES = Set.of("CFG", "ISSUE");
    private static final Set<String> PROMOTE_CLASSES = Set.of("domain", "procedure");
    /** W3 forensics: landed proposals unverified for this long enter the queue. */
    private static final int VERIFY_GRACE_DAYS = 7;
    /** Fixed audit reason stamped by {@link #clearPending} (manual run trigger). */
    public static final String CLEAR_PENDING_REASON = "手動巡檢前清場（manual trigger）";

    private final SupervisorActionRepository actions;
    private final AgentKnowledgeRepository knowledge;
    private final BlockDocMemoRepository docMemos;
    private final BlockDocRepository blockDocs;
    private final ObjectMapper mapper;

    public SupervisorCurationService(SupervisorActionRepository actions,
                                     AgentKnowledgeRepository knowledge,
                                     BlockDocMemoRepository docMemos,
                                     BlockDocRepository blockDocs,
                                     ObjectMapper mapper) {
        this.actions = actions;
        this.knowledge = knowledge;
        this.docMemos = docMemos;
        this.blockDocs = blockDocs;
        this.mapper = mapper;
    }

    // ── propose (sidecar) ───────────────────────────────────────────────

    /** {@code proposal} / {@code narrative} accept a Map OR a JSON string —
     *  the sidecar proposer sends {@code json.dumps} strings (W2 regression:
     *  instanceof-Map coercion silently nulled them → badRequest). Strings
     *  are validated as JSON objects and stored as-is; Maps are serialized. */
    @Transactional
    public Map<String, Object> propose(String actionType, List<?> targetIds,
                                       Object proposal, String rationale,
                                       Map<String, Object> proposerMeta,
                                       Object narrative,
                                       Long supersedes) {
        if (actionType == null || !TYPES.contains(actionType)) {
            throw ApiException.badRequest("action_type must be one of " + TYPES);
        }
        String proposalJson = normalizeJsonObject("proposal", proposal);
        if (proposalJson == null) {
            throw ApiException.badRequest("proposal required");
        }
        // CFG / ISSUE (W3): proposal JSON stored as-is, no target validation —
        // targets live outside this system (config files, issue tracker).
        String targets = JsonUtils.safeWrite(mapper, targetIds == null ? List.of() : targetIds);
        if (actions.existsByActionTypeAndTargetIdsAndStatus(actionType, targets, "proposed")) {
            return Map.of("deduped", true);
        }
        SupervisorActionEntity a = new SupervisorActionEntity();
        a.setActionType(actionType);
        a.setTargetIds(targets);
        a.setProposal(proposalJson);
        a.setRationale(rationale);
        a.setProposerMeta(JsonUtils.safeWrite(mapper, proposerMeta));
        // V75 案情敘事 — optional; NULL keeps the old 3-part frontend rendering
        String narrativeJson = normalizeJsonObject("narrative", narrative);
        if (narrativeJson != null) {
            a.setNarrative(narrativeJson);
        }
        a = actions.save(a);
        // W3 forensics: the new proposal replaces a still-open one. Only a
        // 'proposed' row can be superseded — reviewed rows keep their history.
        if (supersedes != null) {
            final Long newId = a.getId();
            actions.findById(supersedes)
                    .filter(old -> "proposed".equals(old.getStatus()))
                    .ifPresent(old -> {
                        old.setSupersededBy(newId);
                        actions.save(old);
                    });
        }
        // 2026-07-06 信任階梯：agent 提的（策展 = 彙整 agent 記憶）由 Supervisor
        // 自己同意，免人工；Supervisor 自己查出來的（forensics）+ CFG/ISSUE 留
        // IT_ADMIN。護欄：只自動核「增量/可復原」動作，PRUNE（刪除）永遠留人。
        if (shouldAutoApprove(actionType, proposerMeta)) {
            try {
                Map<String, Object> r = approve(a.getId(), SUPERVISOR_AUTO_REVIEWER);
                return Map.of("id", a.getId(), "deduped", false,
                        "auto_approved", true, "commit_result", r);
            } catch (RuntimeException ex) {
                // Auto-commit failed — leave it 'proposed' for a human instead
                // of losing the proposal. (approve() runs in its own tx.)
                log.warn("supervisor auto-approve failed for #{} ({}): {}",
                        a.getId(), actionType, ex.getMessage());
            }
        }
        return Map.of("id", a.getId(), "deduped", false);
    }

    /** id used as reviewer for Supervisor-auto-approved (agent-origin) proposals.
     *  0 is never a real user id — the UI renders it as「Supervisor 自動核」. */
    public static final long SUPERVISOR_AUTO_REVIEWER = 0L;

    /** Additive/reversible curation types Supervisor may land on its own.
     *  PRUNE (deletion) is deliberately excluded — a human decides deletions. */
    private static final Set<String> AUTO_APPROVE_TYPES =
            Set.of("PROMOTE", "DOC_REVISE", "MERGE", "CORRECT");

    private static boolean shouldAutoApprove(String actionType, Map<String, Object> meta) {
        if (!AUTO_APPROVE_TYPES.contains(actionType)) return false;
        String source = meta == null ? "" : String.valueOf(meta.getOrDefault("source", ""));
        // Only curation (aggregating agent-written memories) auto-approves;
        // forensics (Supervisor's own investigation) always goes to IT_ADMIN.
        return "supervisor_curation".equals(source);
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
        OffsetDateTime now = OffsetDateTime.now();
        a.setStatus("approved");
        a.setReviewedBy(reviewerId);
        a.setReviewedAt(now);
        if (MANUAL_LANDING_TYPES.contains(a.getActionType())) {
            // W3 CFG / ISSUE: approval commits NOTHING here — a human lands
            // the change outside this system (config edit / issue tracker),
            // so landed_at/by stay NULL until that landing is recorded.
            a.setCommitResult(JsonUtils.safeWrite(mapper,
                    Map.of("note", "awaiting manual landing")));
        } else {
            Map<String, Object> p = JsonUtils.parseObject(mapper, a.getProposal());
            Map<String, Object> result = switch (a.getActionType()) {
                case "MERGE" -> commitMerge(p);
                case "CORRECT" -> commitCorrect(p);
                case "PRUNE" -> commitPrune(p);
                case "PROMOTE" -> commitPromote(p);
                case "DOC_REVISE" -> commitDocRevise(p, reviewerId);
                default -> throw ApiException.badRequest("unknown action_type " + a.getActionType());
            };
            // V75 landing lifecycle: the per-type commit above succeeded (it
            // throws otherwise, rolling back the status flip with it) — stamp
            // when/who landed.
            a.setLandedAt(now);
            a.setLandedBy(String.valueOf(reviewerId));
            a.setCommitResult(JsonUtils.safeWrite(mapper, result));
        }
        actions.save(a);
        return toDto(a);
    }

    /** Reject with an optional human-stated reason (V75 audit trail). */
    @Transactional
    public Map<String, Object> reject(Long id, Long reviewerId, String reason) {
        SupervisorActionEntity a = actions.findById(id)
                .orElseThrow(() -> ApiException.notFound("proposal " + id));
        if (!"proposed".equals(a.getStatus())) {
            throw ApiException.badRequest("proposal " + id + " already " + a.getStatus());
        }
        a.setStatus("rejected");
        a.setReviewedBy(reviewerId);
        a.setReviewedAt(OffsetDateTime.now());
        if (reason != null && !reason.isBlank()) {
            a.setRejectReason(reason);
        }
        actions.save(a);
        return toDto(a);
    }

    /** Bulk-reject EVERY status=proposed proposal ahead of a manual
     *  Supervisor run — a fresh run re-proposes against the current state,
     *  so a stale queue only confuses the reviewer. Same audit stamping as
     *  {@link #reject} (status flip + reviewer + fixed reason), atomic:
     *  either the whole queue clears or none of it does. Returns the count. */
    @Transactional
    public int clearPending(Long reviewerId) {
        List<SupervisorActionEntity> proposed = actions.findByStatus("proposed");
        OffsetDateTime now = OffsetDateTime.now();
        for (SupervisorActionEntity a : proposed) {
            a.setStatus("rejected");
            a.setReviewedBy(reviewerId);
            a.setReviewedAt(now);
            a.setRejectReason(CLEAR_PENDING_REASON);
        }
        actions.saveAll(proposed);
        return proposed.size();
    }

    // ── W3 forensics: open proposals + post-landing verification ────────

    /** Still-open proposals (status=proposed, not superseded) — the
     *  forensics CLI reads this to decide whether a new finding supersedes
     *  an existing queue entry. Slim rows, same spirit as verifyQueue. */
    @Transactional(readOnly = true)
    public List<Map<String, Object>> openProposals() {
        List<Map<String, Object>> out = new ArrayList<>();
        for (SupervisorActionEntity a
                : actions.findByStatusAndSupersededByIsNullOrderByIdDesc("proposed")) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", a.getId());
            m.put("action_type", a.getActionType());
            m.put("narrative", a.getNarrative() == null ? null
                    : JsonUtils.parseObject(mapper, a.getNarrative()));
            m.put("proposal", JsonUtils.parseObject(mapper, a.getProposal()));
            m.put("created_at", a.getCreatedAt() == null ? null : a.getCreatedAt().toString());
            out.add(m);
        }
        return out;
    }

    /** Landed proposals with no verification after the grace period —
     *  the forensics CLI works this queue. Slim rows on purpose (the CLI
     *  只需要判斷 landing 是否奏效, 不需要完整 review payload). */
    @Transactional(readOnly = true)
    public List<Map<String, Object>> verifyQueue() {
        OffsetDateTime cutoff = OffsetDateTime.now().minusDays(VERIFY_GRACE_DAYS);
        List<Map<String, Object>> out = new ArrayList<>();
        for (SupervisorActionEntity a
                : actions.findByVerifyAtIsNullAndLandedAtBeforeOrderByLandedAtAsc(cutoff)) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", a.getId());
            m.put("action_type", a.getActionType());
            // NOT JsonUtils.parseListOfObjects — target_ids is a JSON array of
            // ids (numbers), and that helper binds List<Map> (→ [] fallback).
            m.put("target_ids", parseIdList(a.getTargetIds()));
            m.put("proposal", JsonUtils.parseObject(mapper, a.getProposal()));
            m.put("narrative", a.getNarrative() == null ? null
                    : JsonUtils.parseObject(mapper, a.getNarrative()));
            m.put("landed_at", a.getLandedAt() == null ? null : a.getLandedAt().toString());
            out.add(m);
        }
        return out;
    }

    /** Record the post-landing verification outcome. Write-once: a second
     *  verify is rejected so the audit trail can't be rewritten. */
    @Transactional
    public Map<String, Object> verify(Long id, String verifyResult) {
        if (verifyResult == null || verifyResult.isBlank()) {
            throw ApiException.badRequest("verify_result required");
        }
        SupervisorActionEntity a = actions.findById(id)
                .orElseThrow(() -> ApiException.notFound("proposal " + id));
        if (a.getLandedAt() == null) {
            throw ApiException.badRequest("proposal " + id + " has not landed — nothing to verify");
        }
        if (a.getVerifyAt() != null) {
            throw ApiException.badRequest("proposal " + id + " already verified at " + a.getVerifyAt());
        }
        a.setVerifyResult(verifyResult);
        a.setVerifyAt(OffsetDateTime.now());
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

    /** DOC_REVISE has two proposer shapes, both valid on human approval:
     *  (a) curation — {block_id, memo_ids[], ...}: promote the pending
     *      block-doc memos that fed this revision.
     *  (b) forensics — {block_id, revised_doc_draft, ...} with NO memo_ids:
     *      the draft was distilled from traces, not from memos.
     *  Either way, when a revised_doc_draft + a target block doc exist we
     *  APPEND the draft to that block's markdown under a dated Supervisor
     *  heading — a human just approved, so this is the landing step (mirrors
     *  PROMOTE creating knowledge, MERGE soft-deleting). Additive only; never
     *  rewrites or deletes existing doc content. */
    private Map<String, Object> commitDocRevise(Map<String, Object> p, Long reviewerId) {
        List<Long> memoIds = asLongList(p.get("memo_ids"));
        String blockId = asNullableString(p.get("block_id"));
        String draft = asNullableString(p.get("revised_doc_draft"));
        if (memoIds.isEmpty() && (draft == null || draft.isBlank())) {
            throw ApiException.badRequest(
                "DOC_REVISE needs either memo_ids or revised_doc_draft");
        }

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

        boolean docApplied = false;
        if (blockId != null && !blockId.isBlank() && draft != null && !draft.isBlank()) {
            Optional<BlockDocEntity> bd =
                blockDocs.findByBlockIdAndBlockVersion(blockId, "1.0.0");
            if (bd.isPresent()) {
                BlockDocEntity doc = bd.get();
                String heading = "\n\n## Supervisor 修訂 ("
                    + OffsetDateTime.now().toLocalDate() + ")\n\n";
                doc.setMarkdown((doc.getMarkdown() == null ? "" : doc.getMarkdown())
                    + heading + draft.strip() + "\n");
                doc.setAutoGenerated(Boolean.FALSE);   // now human-approved
                doc.setLastEditedBy("supervisor#" + reviewerId);
                blockDocs.save(doc);
                docApplied = true;
            }
        }
        return Map.of("memos_promoted", promoted,
                "doc_applied", docApplied,
                "block_id", blockId == null ? "" : blockId);
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
        // V75 narrative + landing lifecycle. narrative stays null (not {})
        // for pre-V75 rows so the frontend can fall back to 3-part rendering.
        m.put("narrative", a.getNarrative() == null ? null
                : JsonUtils.parseObject(mapper, a.getNarrative()));
        m.put("reject_reason", a.getRejectReason());
        m.put("landed_at", a.getLandedAt() == null ? null : a.getLandedAt().toString());
        m.put("landed_by", a.getLandedBy());
        m.put("verify_result", a.getVerifyResult());
        m.put("verify_at", a.getVerifyAt() == null ? null : a.getVerifyAt().toString());
        m.put("superseded_by", a.getSupersededBy());
        return m;
    }

    /** Normalize a Map-or-JSON-string field to its JSON text form.
     *  <ul>
     *    <li>null / blank string / empty map → {@code null} (caller decides
     *        whether the field is required);</li>
     *    <li>Map → serialized via {@link JsonUtils#safeWrite};</li>
     *    <li>String → MUST parse as a JSON object (validated here so a bad
     *        payload fails loudly at the API instead of as a cryptic jsonb
     *        insert error), then stored as-is;</li>
     *    <li>anything else → badRequest.</li>
     *  </ul> */
    private String normalizeJsonObject(String field, Object value) {
        if (value == null) return null;
        if (value instanceof Map<?, ?> m) {
            return m.isEmpty() ? null : JsonUtils.safeWrite(mapper, m);
        }
        if (value instanceof String s) {
            if (s.isBlank()) return null;
            try {
                Map<?, ?> parsed = mapper.readValue(s, Map.class);
                return parsed.isEmpty() ? null : s;   // store the exact string
            } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
                throw ApiException.badRequest(
                        field + " must be a JSON object (got unparseable string): " + e.getOriginalMessage());
            }
        }
        throw ApiException.badRequest(field + " must be a JSON object or object-typed map");
    }

    /** Parse a JSON array of scalar ids ("[1,2]") — empty list on null /
     *  blank / parse failure (same fallback contract as JsonUtils). */
    private List<Object> parseIdList(String json) {
        if (json == null || json.isBlank()) return List.of();
        try {
            return mapper.readValue(json,
                    new com.fasterxml.jackson.core.type.TypeReference<List<Object>>() {});
        } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
            return List.of();
        }
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

    /** null-safe String read — {@code null} in stays {@code null} out
     *  (not the literal "null"). */
    private static String asNullableString(Object o) {
        return o == null ? null : String.valueOf(o);
    }
}
