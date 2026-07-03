package com.aiops.api.api.supervisor;

import com.aiops.api.auth.InternalAuthority;
import com.aiops.api.common.ApiResponse;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeEntity;
import com.aiops.api.domain.agentknowledge.AgentKnowledgeRepository;
import com.aiops.api.domain.agentknowledge.BlockDocMemoEntity;
import com.aiops.api.domain.agentknowledge.BlockDocMemoRepository;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.*;

/**
 * Internal Supervisor endpoints for the sidecar curation proposer (Phase 5).
 *
 * <p>GET /curation-input — everything the proposer LLM needs in one call:
 * draft corrections, live preference/presentation rows (dup candidates),
 * pending doc memos. POST /proposals — queue a proposal (propose-only; a
 * human approves in /supervisor before anything commits).
 */
@RestController
@RequestMapping("/internal/supervisor")
@PreAuthorize(InternalAuthority.REQUIRE_SIDECAR)
public class InternalSupervisorController {

    private final SupervisorCurationService service;
    private final AgentKnowledgeRepository knowledge;
    private final BlockDocMemoRepository docMemos;

    public InternalSupervisorController(SupervisorCurationService service,
                                        AgentKnowledgeRepository knowledge,
                                        BlockDocMemoRepository docMemos) {
        this.service = service;
        this.knowledge = knowledge;
        this.docMemos = docMemos;
    }

    @GetMapping("/curation-input")
    public ApiResponse<Map<String, Object>> curationInput() {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("draft_corrections",
                krows(knowledge.findTop100ByMemoClassAndActiveOrderByIdDesc("correction", false)));
        out.put("live_preferences",
                krows(knowledge.findTop100ByMemoClassAndActiveOrderByIdDesc("preference", true)));
        out.put("live_presentations",
                krows(knowledge.findTop100ByMemoClassAndActiveOrderByIdDesc("presentation", true)));
        List<Map<String, Object>> memos = new ArrayList<>();
        for (BlockDocMemoEntity m : docMemos.findTop100ByStatusOrderByIdDesc("pending")) {
            Map<String, Object> r = new LinkedHashMap<>();
            r.put("id", m.getId());
            r.put("block_id", m.getBlockId());
            r.put("param", m.getParam());
            r.put("memo", m.getMemo());
            r.put("from_episode", m.getFromEpisode());
            memos.add(r);
        }
        out.put("pending_doc_memos", memos);
        return ApiResponse.ok(out);
    }

    @PostMapping("/proposals")
    public ApiResponse<Map<String, Object>> propose(@RequestBody Map<String, Object> body) {
        Object targets = body.get("target_ids");
        @SuppressWarnings("unchecked")
        Map<String, Object> proposal = body.get("proposal") instanceof Map<?, ?> m
                ? (Map<String, Object>) m : null;
        @SuppressWarnings("unchecked")
        Map<String, Object> meta = body.get("proposer_meta") instanceof Map<?, ?> m2
                ? (Map<String, Object>) m2 : null;
        return ApiResponse.ok(service.propose(
                body.get("action_type") == null ? null : String.valueOf(body.get("action_type")),
                targets instanceof List<?> l ? l : List.of(),
                proposal,
                body.get("rationale") == null ? null : String.valueOf(body.get("rationale")),
                meta));
    }

    private static List<Map<String, Object>> krows(List<AgentKnowledgeEntity> rows) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (AgentKnowledgeEntity e : rows) {
            Map<String, Object> r = new LinkedHashMap<>();
            r.put("id", e.getId());
            r.put("title", e.getTitle());
            r.put("body", e.getBody());
            r.put("memo_class", e.getMemoClass());
            r.put("written_by", e.getWrittenBy());
            r.put("applies_to", e.getAppliesTo());
            r.put("uses", e.getUses());
            out.add(r);
        }
        return out;
    }
}
