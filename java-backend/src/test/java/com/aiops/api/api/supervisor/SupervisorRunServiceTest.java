package com.aiops.api.api.supervisor;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.common.ApiException;
import com.aiops.api.sidecar.PythonSidecarClient;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

/**
 * Pure-Mockito tests — manual Supervisor run trigger. Focus: forward-body
 * fidelity (snake_case keys, clear_pending never leaks to the sidecar),
 * cleared-count prepending, validate-before-clear ordering, and the 409
 * running-conflict mapping.
 */
class SupervisorRunServiceTest {

    private SupervisorCurationService curation;
    private PythonSidecarClient sidecar;
    private SupervisorRunService service;
    private final AuthPrincipal admin = new AuthPrincipal(9L, "itadmin", Set.of());

    @BeforeEach
    void setUp() {
        curation = mock(SupervisorCurationService.class);
        sidecar = mock(PythonSidecarClient.class);
        service = new SupervisorRunService(curation, sidecar, new ObjectMapper());
    }

    private void sidecarAnswers(Map<String, Object> body) {
        doReturn(Mono.just(body)).when(sidecar)
                .postJson(anyString(), any(), eq(Map.class), any());
    }

    // ── trigger: forward + prepend cleared ──────────────────────────────

    @Test
    void trigger_forwardsBodyAndPrependsClearedCount() {
        when(curation.clearPending(9L)).thenReturn(3);
        sidecarAnswers(Map.of("run_id", "r-77", "started", true));

        Map<String, Object> out = service.trigger(Map.of(
                "kind", "curation", "days", 7, "max_deep_dives", 2,
                "clear_pending", true), admin);

        assertThat(out).containsEntry("cleared", 3)
                .containsEntry("run_id", "r-77")
                .containsEntry("started", true);

        ArgumentCaptor<Object> body = ArgumentCaptor.forClass(Object.class);
        verify(sidecar).postJson(eq(SupervisorRunService.RUNS_PATH), body.capture(),
                eq(Map.class), eq(admin));
        assertThat(body.getValue()).isEqualTo(Map.of(
                "kind", "curation", "days", 7, "max_deep_dives", 2));
        // clear_pending is a Java-side concern — never forwarded
    }

    @Test
    void trigger_withoutClearPendingSkipsClearAndReportsZero() {
        sidecarAnswers(Map.of("run_id", "r-1", "started", true));

        Map<String, Object> out = service.trigger(Map.of("kind", "curation"), admin);

        assertThat(out).containsEntry("cleared", 0).containsEntry("started", true);
        verify(curation, never()).clearPending(any());
        // optional fields absent → not forwarded (sidecar applies its defaults)
        ArgumentCaptor<Object> body = ArgumentCaptor.forClass(Object.class);
        verify(sidecar).postJson(anyString(), body.capture(), eq(Map.class), any());
        assertThat(body.getValue()).isEqualTo(Map.of("kind", "curation"));
    }

    // ── validate BEFORE clear ───────────────────────────────────────────

    @Test
    void trigger_missingKindFailsWithoutClearing() {
        assertThatThrownBy(() -> service.trigger(
                Map.of("clear_pending", true), admin))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("kind");
        assertThatThrownBy(() -> service.trigger(
                Map.of("kind", "curation", "days", "not-a-number", "clear_pending", true), admin))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("days");
        // string "true" must fail loudly, not silently skip the clear
        assertThatThrownBy(() -> service.trigger(
                Map.of("kind", "curation", "clear_pending", "true"), admin))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("clear_pending");
        verify(curation, never()).clearPending(any());   // invalid request never clears
        verifyNoInteractions(sidecar);
    }

    // ── 409 running conflict ────────────────────────────────────────────

    @Test
    void trigger_sidecar409MapsToConflictWithClearedAndSidecarBody() {
        when(curation.clearPending(9L)).thenReturn(2);
        WebClientResponseException conflict = WebClientResponseException.create(
                409, "Conflict", HttpHeaders.EMPTY,
                "{\"running\": true, \"run_id\": \"r-active\"}".getBytes(StandardCharsets.UTF_8),
                StandardCharsets.UTF_8);
        doReturn(Mono.error(conflict)).when(sidecar)
                .postJson(anyString(), any(), eq(Map.class), any());

        assertThatThrownBy(() -> service.trigger(
                Map.of("kind", "curation", "clear_pending", true), admin))
                .isInstanceOfSatisfying(ApiException.class, ex -> {
                    assertThat(ex.status()).isEqualTo(HttpStatus.CONFLICT);
                    assertThat(ex.code()).isEqualTo("supervisor_run_in_progress");
                    @SuppressWarnings("unchecked")
                    Map<String, Object> details = (Map<String, Object>) ex.details();
                    // clear already committed — the caller must see the count
                    assertThat(details).containsEntry("cleared", 2)
                            .containsEntry("running", true)
                            .containsEntry("run_id", "r-active");
                });
    }

    // ── status passthrough ──────────────────────────────────────────────

    @Test
    void status_passesThroughSidecarJson() {
        doReturn(Mono.just(Map.of("running", false, "last_run_id", "r-9")))
                .when(sidecar).getJson(eq(SupervisorRunService.RUNS_STATUS_PATH),
                        eq(Map.class), eq(admin));

        Map<String, Object> out = service.status(admin);

        assertThat(out).containsEntry("running", false)
                .containsEntry("last_run_id", "r-9");
    }
}
