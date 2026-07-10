package com.aiops.api.api.mcp;

import com.aiops.api.domain.mcp.McpCapabilitySettingsEntity;
import com.aiops.api.domain.mcp.McpCapabilitySettingsRepository;
import com.aiops.api.domain.mcp.McpDefinitionEntity;
import com.aiops.api.domain.mcp.McpDefinitionRepository;
import com.aiops.api.domain.skillv2.SkillV2Entity;
import com.aiops.api.domain.skillv2.SkillV2Repository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * MCP capability registry catalog (Phase 2). Merges the three capability
 * sources into one list, each annotated with its exposure ({@code isPublic})
 * and write flag ({@code isWrite}):
 *
 * <ul>
 *   <li><b>builtin</b> — from the MCP server's {@code /capabilities} manifest
 *       (single source; is_write comes from there).</li>
 *   <li><b>domain_skill</b> — published pipelines in {@code skills_v2}; invoking
 *       one is read/compute (is_write=false); its lifecycle ops are builtin tools.</li>
 *   <li><b>external</b> — System MCPs ({@code mcp_definitions}); calling an
 *       external API is a fetch (is_write=false).</li>
 * </ul>
 *
 * Exposure is a LEFT JOIN onto {@code mcp_capability_settings}: no row ⇒ public
 * (spec decision 4, current exposure preserved). {@link #setExposure} upserts.
 */
@Service
public class McpCapabilityService {

    private static final Logger log = LoggerFactory.getLogger(McpCapabilityService.class);

    private final McpCapabilitySettingsRepository settingsRepo;
    private final SkillV2Repository skillRepo;
    private final McpDefinitionRepository mcpRepo;
    private final WebClient mcpServer;

    public McpCapabilityService(McpCapabilitySettingsRepository settingsRepo,
                                SkillV2Repository skillRepo,
                                McpDefinitionRepository mcpRepo,
                                @Value("${aiops.mcp-server-url:http://localhost:8060}") String mcpServerUrl) {
        this.settingsRepo = settingsRepo;
        this.skillRepo = skillRepo;
        this.mcpRepo = mcpRepo;
        this.mcpServer = WebClient.builder().baseUrl(mcpServerUrl).build();
    }

    /** One catalog row. */
    public record Capability(String key, String name, String description,
                             String kind, boolean isWrite, boolean isPublic,
                             boolean isInternal, boolean coordinatorEligible) {}

    // Coordinator-eligible built-in tools: query / status / run-ready-made only.
    // The pipeline-CONSTRUCTION primitives (list_blocks / validate / preview /
    // execute / save_pipeline / …) are DELIBERATELY absent — they are Planner &
    // Builder's job; granting them to the Coordinator would let it bypass them.
    private static final java.util.Set<String> COORDINATOR_BUILTINS = java.util.Set.of(
            "list_alarms", "get_alarm_detail", "list_agent_knowledge",
            "list_supervisor_proposals", "list_skills_v2", "get_skill_v2",
            "list_agent_activity", "get_agent_activity",
            "check_skill_ready_for_role", "list_event_sources",
            // Alarm 處理能力包 (2026-07-10): history/stats reads + handling
            // writes. The writes never execute server-side from the agent —
            // they emit a confirm card and the browser performs the POST under
            // the user's JWT (role gates like resolve=ADMIN_OR_PE apply as-is).
            "query_alarms", "get_alarm_stats",
            "ack_alarm", "dispose_alarm", "resolve_alarm");

    /** Whether a capability needs an explicit 對內 grant to reach the Coordinator.
     *  Only the platform-meta READ built-ins do. Domain skills are the agent's
     *  DEFAULT repertoire (always usable via invoke_skill, no grant). External
     *  System MCPs reach the agent ONLY as their V54-derived Skills — a raw MCP
     *  is never given, so it is not grantable here either. */
    static boolean coordinatorEligible(String kind, String key) {
        return "builtin".equals(kind) && COORDINATOR_BUILTINS.contains(key);
    }

    /**
     * Full catalog across all three sources, each with effective exposure.
     * Fail-open: if a source is unreachable it is logged + skipped, never fails
     * the whole catalog (admin still sees what IS reachable).
     */
    public List<Capability> catalog() {
        Map<String, McpCapabilitySettingsEntity> settings = new LinkedHashMap<>();
        for (McpCapabilitySettingsEntity s : settingsRepo.findAll()) {
            settings.put(s.getCapabilityKey(), s);
        }
        List<Capability> out = new ArrayList<>();

        // builtin — from the MCP server manifest
        for (Map<String, Object> t : fetchBuiltinManifest()) {
            String key = String.valueOf(t.get("key"));
            out.add(row(key, String.valueOf(t.getOrDefault("name", key)),
                    String.valueOf(t.getOrDefault("description", "")), "builtin",
                    Boolean.TRUE.equals(t.get("is_write")), settings.get(key)));
        }
        // domain skills — invoke is read/compute
        for (SkillV2Entity sk : skillRepo.findAll()) {
            String key = sk.getSlug();
            out.add(row(key, sk.getName(),
                    sk.getSub() != null && !sk.getSub().isBlank() ? sk.getSub() : sk.getNl(),
                    "domain_skill", false, settings.get(key)));
        }
        // external — System MCPs; calling is a fetch
        for (McpDefinitionEntity m : mcpRepo.findAll()) {
            String key = m.getName();
            out.add(row(key, m.getName(), m.getDescription(), "external", false, settings.get(key)));
        }
        return out;
    }

    private static Capability row(String key, String name, String desc, String kind,
                                  boolean isWrite, McpCapabilitySettingsEntity s) {
        // no settings row ⇒ public by default (decision 4); is_internal always
        // defaults false (Coordinator opt-in). is_internal only honoured when
        // the capability is actually coordinator-eligible.
        boolean elig = coordinatorEligible(kind, key);
        boolean pub = s == null || Boolean.TRUE.equals(s.getIsPublic());
        boolean internal = elig && s != null && Boolean.TRUE.equals(s.getIsInternal());
        return new Capability(key, name, desc, kind, isWrite, pub, internal, elig);
    }

    /** Set a capability's exposure. Upserts the overlay row. Either flag may be
     *  null (leave unchanged). is_internal is ignored for non-eligible keys. */
    @Transactional
    public Capability setExposure(String key, String kind, Boolean isPublic,
                                  Boolean isInternal, String updatedBy) {
        McpCapabilitySettingsEntity r = settingsRepo.findByCapabilityKey(key)
                .orElseGet(McpCapabilitySettingsEntity::new);
        r.setCapabilityKey(key);
        r.setKind(kind);
        if (isPublic != null) r.setIsPublic(isPublic);
        if (isInternal != null) {
            r.setIsInternal(coordinatorEligible(kind, key) && isInternal);
        }
        r.setUpdatedBy(updatedBy);
        settingsRepo.save(r);
        return catalog().stream().filter(c -> c.key().equals(key)).findFirst()
                .orElse(new Capability(key, key, "", kind, false,
                        isPublic == null || isPublic, false, coordinatorEligible(kind, key)));
    }

    /** Capabilities granted to the internal Coordinator agent (is_internal +
     *  eligible). The sidecar loads these on top of its curated core tools. */
    public List<Capability> agentTools() {
        return catalog().stream().filter(Capability::isInternal).toList();
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> fetchBuiltinManifest() {
        try {
            Map<String, Object> resp = mcpServer.get().uri("/capabilities").retrieve()
                    .bodyToMono(Map.class).timeout(Duration.ofSeconds(5)).block();
            Object caps = resp == null ? null : resp.get("capabilities");
            if (caps instanceof List<?> list) {
                List<Map<String, Object>> out = new ArrayList<>();
                for (Object o : list) {
                    if (o instanceof Map<?, ?> mm) out.add((Map<String, Object>) mm);
                }
                return out;
            }
        } catch (RuntimeException ex) {
            log.warn("MCP capability manifest fetch failed ({}); catalog omits built-in tools", ex.toString());
        }
        return List.of();
    }
}
