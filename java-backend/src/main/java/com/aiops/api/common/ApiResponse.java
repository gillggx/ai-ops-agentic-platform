package com.aiops.api.common;

import java.time.Instant;

public record ApiResponse<T>(boolean ok, T data, ErrorDetail error, Instant timestamp) {

	public static <T> ApiResponse<T> ok(T data) {
		return new ApiResponse<>(true, data, null, Instant.now());
	}

	public static <T> ApiResponse<T> fail(String code, String message) {
		return new ApiResponse<>(false, null, new ErrorDetail(code, message, null), Instant.now());
	}

	public static <T> ApiResponse<T> fail(String code, String message, Object details) {
		return new ApiResponse<>(false, null, new ErrorDetail(code, message, details), Instant.now());
	}

	public record ErrorDetail(String code, String message, Object details) {}
}
