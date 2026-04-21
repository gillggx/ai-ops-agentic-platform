package com.aiops.api.api.health;

import com.aiops.api.common.ApiResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/api/v1/health")
public class HealthController {

	@Value("${spring.application.name}")
	private String appName;

	@Value("${spring.profiles.active:default}")
	private String profile;

	@GetMapping
	public ApiResponse<Map<String, Object>> health() {
		return ApiResponse.ok(Map.of(
				"service", appName,
				"profile", profile,
				"status", "UP"
		));
	}
}
