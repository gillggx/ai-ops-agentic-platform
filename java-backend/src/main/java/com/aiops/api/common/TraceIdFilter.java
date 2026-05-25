package com.aiops.api.common;

import jakarta.servlet.Filter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.util.UUID;
import java.util.regex.Pattern;

/**
 * Trace-id correlation filter.
 *
 * <p>Reads {@code X-Trace-ID} from inbound requests and puts it in SLF4J MDC
 * under key {@code trace_id} so {@code logback-spring.xml} can include it in
 * every JSON log line. Generates a new UUID4 when the header is absent or
 * malformed. Echoes the resulting id back in the response header so the
 * caller (and downstream services) can use the same value.</p>
 *
 * <p>Ordered HIGHEST_PRECEDENCE so the id is present for auth / business
 * filters that log on this request.</p>
 *
 * <p>Untrusted callers: header value is validated against
 * {@code [A-Za-z0-9_-]{1,128}} to prevent log injection / oversized headers.</p>
 *
 * <p>Schema: see {@code docs/logging-schema.md}.</p>
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class TraceIdFilter implements Filter {

    public static final String MDC_KEY = "trace_id";
    public static final String HEADER = "X-Trace-ID";
    private static final Pattern VALID = Pattern.compile("[A-Za-z0-9_-]{1,128}");

    @Override
    public void doFilter(ServletRequest req, ServletResponse resp, FilterChain chain)
            throws IOException, ServletException {
        HttpServletRequest http = (HttpServletRequest) req;
        HttpServletResponse httpResp = (HttpServletResponse) resp;

        String inbound = http.getHeader(HEADER);
        String tid = (inbound != null && VALID.matcher(inbound).matches())
                ? inbound
                : UUID.randomUUID().toString();

        MDC.put(MDC_KEY, tid);
        httpResp.setHeader(HEADER, tid);
        try {
            chain.doFilter(req, resp);
        } finally {
            MDC.remove(MDC_KEY);
        }
    }
}
