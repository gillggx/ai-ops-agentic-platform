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
                             String kind, boolean isWrite, boolean isPublic) {}

    /**
     * Full catalog across all three sources, each with effective exposure.
     * Fail-open: if a source is unreachable it is logged + skipped, never fails
     * the whole catalog (admin still sees what IS reachable).
     */
    public List<Capability> catalog() {
        Map<String, Boolean> exposure = new LinkedHashMap<>();
        for (McpCapabilitySettingsEntity s : settingsRepo.findAll()) {
            exposure.put(s.getCapabilityKey(), Boolean.TRUE.equals(s.getIsPublic()));
        }
        List<Capability> out = new ArrayList<>();

        // builtin — from the MCP server manifest
        for (Map<String, Object> t : fetchBuiltinManifest()) {
            String key = String.valueOf(t.get("key"));
            out.add(new Capability(key, String.valueOf(t.getOrDefault("name", key)),
                    String.valueOf(t.getOrDefault("description", "")), "builtin",
                    Boolean.TRUE.equals(t.get("is_write")),
                    exposure.getOrDefault(key, Boolean.TRUE)));
        }
        // domain skills — invoke is read/compute
        for (SkillV2Entity sk : skillRepo.findAll()) {
            String key = sk.getSlug();
            out.add(new Capability(key, sk.getName(),
                    sk.getSub() != null && !sk.getSub().isBlank() ? sk.getSub() : sk.getNl(),
                    "domain_skill", false, exposure.getOrDefault(key, Boolean.TRUE)));
        }
        // external — System MCPs; calling is a fetch
        for (McpDefinitionEntity m : mcpRepo.findAll()) {
            String key = m.getName();
            out.add(new Capability(key, m.getName(), m.getDescription(),
                    "external", false, exposure.getOrDefault(key, Boolean.TRUE)));
        }
        return out;
    }

    /** Set a capability's public/private. Upserts the overlay row. */
    @Transactional
    public Capability setExposure(String key, String kind, boolean isPublic, String updatedBy) {
        McpCapabilitySettingsEntity row = settingsRepo.findByCapabilityKey(key)
                .orElseGet(McpCapabilitySettingsEntity::new);
        row.setCapabilityKey(key);
        row.setKind(kind);
        row.setIsPublic(isPublic);
        row.setUpdatedBy(updatedBy);
        settingsRepo.save(row);
        // Return the merged view for this key so the UI can reflect it directly.
        return catalog().stream().filter(c -> c.key().equals(key)).findFirst()
                .orElse(new Capability(key, key, "", kind, false, isPublic));
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
