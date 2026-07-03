package com.aiops.api.api.agentepisode;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Reads a BuildTracer JSON (written by the sidecar to BUILDER_TRACE_DIR) and
 * extracts the per-round LLM calls for the Agent Activity "trace detail" view.
 * The sidecar and Java share the host filesystem (single-host systemd), so the
 * trace_file path stored on the episode is directly readable here.
 *
 * <p>Pure best-effort: any IO/parse failure returns null so the caller falls
 * back to the steps view. Never throws.
 */
final class TraceFileReader {

    private TraceFileReader() {}

    /** @return list of {phase_id, round, node, user_msg, raw_response, input_tokens,
     *          output_tokens, cache_read} or null when the file can't be read. */
    static List<Map<String, Object>> readLlmCalls(ObjectMapper mapper, String tracePath) {
        if (tracePath == null || tracePath.isBlank()) return null;
        try {
            Path p = Path.of(tracePath);
            if (!Files.isReadable(p)) return null;
            JsonNode root = mapper.readTree(Files.readString(p));
            JsonNode calls = root.get("llm_calls");
            if (calls == null || !calls.isArray()) return null;
            List<Map<String, Object>> out = new ArrayList<>();
            for (JsonNode c : calls) {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("node", txt(c, "node"));
                m.put("phase_id", txt(c, "phase_id"));
                m.put("round", num(c, "round"));
                m.put("user_msg", txt(c, "user_msg"));         // the prompt run
                m.put("raw_response", txt(c, "raw_response"));  // the output
                m.put("input_tokens", num(c, "input_tokens"));
                m.put("output_tokens", num(c, "output_tokens"));
                m.put("cache_read", num(c, "cache_read_input_tokens"));
                m.put("finish_reason", txt(c, "finish_reason"));
                out.add(m);
            }
            return out;
        } catch (Exception ex) {  // noqa — best-effort read
            return null;
        }
    }

    private static Object txt(JsonNode n, String f) {
        JsonNode v = n.get(f);
        return v == null || v.isNull() ? null : v.asText();
    }

    private static Object num(JsonNode n, String f) {
        JsonNode v = n.get(f);
        return v == null || v.isNull() || !v.isNumber() ? null : v.asInt();
    }
}
