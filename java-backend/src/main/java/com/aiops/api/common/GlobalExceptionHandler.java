package com.aiops.api.common;

import jakarta.validation.ConstraintViolationException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.authorization.AuthorizationDeniedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.util.stream.Collectors;

@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

	@ExceptionHandler(ApiException.class)
	public ResponseEntity<ApiResponse<Void>> handleApi(ApiException ex) {
		return ResponseEntity.status(ex.status())
				.body(ApiResponse.fail(ex.code(), ex.getMessage(), ex.details()));
	}

	@ExceptionHandler(MethodArgumentNotValidException.class)
	public ResponseEntity<ApiResponse<Void>> handleValidation(MethodArgumentNotValidException ex) {
		String msg = ex.getBindingResult().getFieldErrors().stream()
				.map(e -> e.getField() + ": " + e.getDefaultMessage())
				.collect(Collectors.joining("; "));
		return ResponseEntity.badRequest()
				.body(ApiResponse.fail("validation_error", msg));
	}

	@ExceptionHandler(ConstraintViolationException.class)
	public ResponseEntity<ApiResponse<Void>> handleConstraint(ConstraintViolationException ex) {
		return ResponseEntity.badRequest()
				.body(ApiResponse.fail("validation_error", ex.getMessage()));
	}

	@ExceptionHandler({AccessDeniedException.class, AuthorizationDeniedException.class})
	public ResponseEntity<ApiResponse<Void>> handleAccessDenied(Exception ex) {
		return ResponseEntity.status(HttpStatus.FORBIDDEN)
				.body(ApiResponse.fail("forbidden", "insufficient role"));
	}

	/**
	 * Propagates sidecar errors back to the frontend with a usable status + the
	 * original error body when available. Without this, any non-2xx from the
	 * Python sidecar collapses to a 500 "Internal server error".
	 */
	@ExceptionHandler(WebClientResponseException.class)
	public ResponseEntity<ApiResponse<Void>> handleSidecarError(WebClientResponseException ex) {
		HttpStatus status = HttpStatus.resolve(ex.getStatusCode().value());
		if (status == null || status.is5xxServerError() && !ex.getStatusCode().is4xxClientError()) {
			status = HttpStatus.BAD_GATEWAY;
		} else if (ex.getStatusCode().is4xxClientError()) {
			status = HttpStatus.valueOf(ex.getStatusCode().value());
		}
		String responseBody = ex.getResponseBodyAsString();
		String message = responseBody != null && !responseBody.isBlank()
				? responseBody.length() > 500 ? responseBody.substring(0, 500) : responseBody
				: ex.getMessage();
		log.warn("sidecar upstream {} → mapping to {}: {}", ex.getStatusCode(), status, message);
		return ResponseEntity.status(status)
				.body(ApiResponse.fail("sidecar_upstream_error", message));
	}

	@ExceptionHandler(Exception.class)
	public ResponseEntity<ApiResponse<Void>> handleGeneric(Exception ex) {
		log.error("Unhandled exception", ex);
		return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
				.body(ApiResponse.fail("internal_error", "Internal server error"));
	}
}
