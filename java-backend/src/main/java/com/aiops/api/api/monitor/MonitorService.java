package com.aiops.api.api.monitor;

import com.aiops.api.common.ApiException;
import com.aiops.api.common.JsonUtils;
import com.aiops.api.domain.agentepisode.AgentEpisodeRepository;
import com.aiops.api.domain.agentepisode.AgentStepRepository;
import com.aiops.api.domain.agentknowledge.BlockDocMemoRepository;
import com.aiops.api.domain.monitor.MonitorRequestEntity;
import com.aiops.api.domain.monitor.MonitorRequestRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.*;

/**
 * Monitor requesters (Phase 6, option A: system self-health, V73).
 *
 * <p>Deterministic scan over OUR agents' own observability data — no LLM, no
 * fab data (that is auto-patrol's job). Three metrics:
 * <ul>
 *   <li>DOC_GAP — a block accumulated ≥ K pending doc memos → its doc is
 *       likely under-specified.</li>
 *   <li>DIVERGENCE — ≥ K self-OK-but-user-rejected builds in the window →
 *       the verifier/plan quality drifted.</li>
 *   <li>REPAIR_HANDOVER — ≥ K repair handovers (self-fix failed) in the
 *       window → systematic capability gap.</li>
 * </ul>
 *
 * <p>Findings become REQUEST rows (status=open, deduped per kind+subject).
 * A human approves in /supervisor before the prepared instruction is
 * launched at the Planner — same human-in-the-loop as curation.
 */
@Service
public class MonitorService {

    // Thresholds — deliberately conservative first cut; env-tunable later if needed.
    static final long DOC_GAP_MIN_MEMOS = 3;
    static final long DIVERGENCE_MIN = 2;
    static final long HANDOVER_MIN = 3;
    static final int WINDOW_DAYS = 7;

    private final MonitorRequestRepository requests;
    private final BlockDocMemoRepository docMemos;
    private final AgentEpisodeRepository episodes;
    private final AgentStepRepository steps;
    private final ObjectMapper mapper;

    public MonitorService(MonitorRequestRepository requests,
                          BlockDocMemoRepository docMemos,
                          AgentEpisodeRepository episodes,
                          AgentStepRepository steps,
                          ObjectMapper mapper) {
        this.requests = requests;
        this.docMemos = docMemos;
        this.episodes = episodes;
        this.steps = steps;
        this.mapper = mapper;
    }

    /** One deterministic scan; returns {created, skipped_dedup, findings}. */
    @Transactional
    public Map<String, Object> scan() {
        OffsetDateTime cutoff = OffsetDateTime.now().minusDays(WINDOW_DAYS);
        int created = 0, deduped = 0;
        List<Map<String, Object>> findings = new ArrayList<>();

        // 1) DOC_GAP per block
        for (Object[] row : docMemos.pendingCountsByBlock(DOC_GAP_MIN_MEMOS)) {
            String blockId = String.valueOf(row[0]);
            long n = ((Number) row[1]).longValue();
            Map<String, Object> ev = Map.of(
                    "metric", "pending_doc_memos", "value", n,
                    "threshold", DOC_GAP_MIN_MEMOS, "window_days", "all-time");
            String instr = "檢視 block「" + blockId + "」的文件:累積 " + n
                    + " 筆 pending doc memo,表示 agent 反覆在同一 block 踩坑。"
                    + "請彙整備忘、補強 description/param_schema/examples(走 DOC_REVISE 草案流程)。";
            int r = file("DOC_GAP", blockId, ev, instr);
            created += r; deduped += (1 - r);
            findings.add(Map.of("kind", "DOC_GAP", "subject", blockId, "value", n));
        }

        // 2) DIVERGENCE in window
        long div = episodes.countByDivergenceTrueAndStartedAtAfter(cutoff);
        if (div >= DIVERGENCE_MIN) {
            long total = episodes.countByStartedAtAfter(cutoff);
            Map<String, Object> ev = Map.of(
                    "metric", "divergence_count", "value", div,
                    "total_episodes", total,
                    "threshold", DIVERGENCE_MIN, "window_days", WINDOW_DAYS);
            String instr = "最近 " + WINDOW_DAYS + " 天有 " + div + "/" + total
                    + " 個 build 系統自評 OK 但被 user 否決(divergence)。"
                    + "請檢視 /agent-activity 對應 episodes,歸納 verifier 漏判的 pattern。";
            int r = file("DIVERGENCE", "divergence_" + WINDOW_DAYS + "d", ev, instr);
            created += r; deduped += (1 - r);
            findings.add(Map.of("kind", "DIVERGENCE", "value", div));
        }

        // 3) REPAIR_HANDOVER in window
        long ho = steps.countRepairHandoversAfter(cutoff);
        if (ho >= HANDOVER_MIN) {
            long allRepairs = steps.countByEventTypeAndTsAfter("repair_outcome", cutoff);
            Map<String, Object> ev = Map.of(
                    "metric", "repair_handover_count", "value", ho,
                    "total_repairs", allRepairs,
                    "threshold", HANDOVER_MIN, "window_days", WINDOW_DAYS);
            String instr = "最近 " + WINDOW_DAYS + " 天 Repair 有 " + ho + "/" + allRepairs
                    + " 次以 handover 收場(自我修復失敗)。"
                    + "請檢視 handover episodes 的共通根因(block 能力缺口 / doc 缺口 / plan 過度切分)。";
            int r = file("REPAIR_HANDOVER", "handover_" + WINDOW_DAYS + "d", ev, instr);
            created += r; deduped += (1 - r);
            findings.add(Map.of("kind", "REPAIR_HANDOVER", "value", ho));
        }

        return Map.of("created", created, "deduped", deduped, "findings", findings);
    }

    /** @return 1 if a new request row was created, 0 if deduped. */
    private int file(String kind, String subject, Map<String, Object> evidence,
                     String instruction) {
        if (requests.existsByKindAndSubjectAndStatus(kind, subject, "open")) return 0;
        MonitorRequestEntity r = new MonitorRequestEntity();
        r.setKind(kind);
        r.setSubject(subject);
        r.setEvidence(JsonUtils.safeWrite(mapper, evidence));
        r.setSuggestedInstruction(instruction);
        requests.save(r);
        return 1;
    }

    // ── list / review ───────────────────────────────────────────────────

    @Transactional(readOnly = true)
    public List<Map<String, Object>> list(String status) {
        List<MonitorRequestEntity> rows = (status == null || status.isBlank())
                ? requests.findTop200ByOrderByIdDesc()
                : requests.findTop200ByStatusOrderByIdDesc(status);
        List<Map<String, Object>> out = new ArrayList<>();
        for (MonitorRequestEntity r : rows) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", r.getId());
            m.put("kind", r.getKind());
            m.put("subject", r.getSubject());
            m.put("evidence", JsonUtils.parseObject(mapper, r.getEvidence()));
            m.put("suggested_instruction", r.getSuggestedInstruction());
            m.put("status", r.getStatus());
            m.put("created_at", r.getCreatedAt() == null ? null : r.getCreatedAt().toString());
            m.put("reviewed_by", r.getReviewedBy());
            m.put("reviewed_at", r.getReviewedAt() == null ? null : r.getReviewedAt().toString());
            out.add(m);
        }
        return out;
    }

    @Transactional
    public Map<String, Object> review(Long id, Long reviewerId, boolean approve) {
        MonitorRequestEntity r = requests.findById(id)
                .orElseThrow(() -> ApiException.notFound("monitor request " + id));
        if (!"open".equals(r.getStatus())) {
            throw ApiException.badRequest("request " + id + " already " + r.getStatus());
        }
        r.setStatus(approve ? "approved" : "dismissed");
        r.setReviewedBy(reviewerId);
        r.setReviewedAt(OffsetDateTime.now());
        requests.save(r);
        return Map.of("id", r.getId(), "status", r.getStatus(),
                "suggested_instruction",
                r.getSuggestedInstruction() == null ? "" : r.getSuggestedInstruction());
    }
}
