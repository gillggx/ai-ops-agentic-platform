package com.aiops.api.common;

import org.springframework.http.HttpStatus;

public class ApiException extends RuntimeException {

	private final HttpStatus status;
	private final String code;
	private final transient Object details;

	public ApiException(HttpStatus status, String code, String message) {
		this(status, code, message, null);
	}

	public ApiException(HttpStatus status, String code, String message, Object details) {
		super(message);
		this.status = status;
		this.code = code;
		this.details = details;
	}

	public HttpStatus status() { return status; }
	public String code() { return code; }
	public Object details() { return details; }

	public static ApiException notFound(String what) {
		return new ApiException(HttpStatus.NOT_FOUND, "not_found", what + " not found");
	}

	public static ApiException badRequest(String message) {
		return new ApiException(HttpStatus.BAD_REQUEST, "bad_request", message);
	}

	public static ApiException forbidden(String message) {
		return new ApiException(HttpStatus.FORBIDDEN, "forbidden", message);
	}

	public static ApiException conflict(String message) {
		return new ApiException(HttpStatus.CONFLICT, "conflict", message);
	}
}
