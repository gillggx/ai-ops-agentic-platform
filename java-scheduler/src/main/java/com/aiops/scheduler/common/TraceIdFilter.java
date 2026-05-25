package com.aiops.scheduler.common;

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
 * Scheduler-side copy of {@code com.aiops.api.common.TraceIdFilter}.
 * Both services share the same X-Trace-ID convention; the duplication
 * keeps the modules independently deployable (no shared library yet).
 *
 * <p>For background cron jobs (no inbound HTTP), see
 * {@code AutoPatrolSchedulerService} where each job-start sets a
 * {@code task_<uuid>} id in MDC for the duration of the run.</p>
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
