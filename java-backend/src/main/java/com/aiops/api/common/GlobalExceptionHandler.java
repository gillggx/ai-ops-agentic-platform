package com.aiops.api.common;

import jakarta.validation.ConstraintViolationException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

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

	@ExceptionHandler(Exception.class)
	public ResponseEntity<ApiResponse<Void>> handleGeneric(Exception ex) {
		log.error("Unhandled exception", ex);
		return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
				.body(ApiResponse.fail("internal_error", "Internal server error"));
	}
}
