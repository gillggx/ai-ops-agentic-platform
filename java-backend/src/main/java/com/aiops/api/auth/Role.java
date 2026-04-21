package com.aiops.api.auth;

import java.util.Arrays;
import java.util.Optional;

/**
 * Platform roles, per SPEC §2.6.1.
 *
 * <ul>
 *   <li>{@link #IT_ADMIN} — platform operator: user management, MCP registration,
 *       system parameters, deploy, audit log access</li>
 *   <li>{@link #PE} — Process Engineer: build Skills / Pipelines / Alarm rules,
 *       dispatch, analyse events</li>
 *   <li>{@link #ON_DUTY} — on-duty engineer: view alarms, ack events, read-only
 *       briefing — no destructive writes</li>
 * </ul>
 */
public enum Role {
	IT_ADMIN,
	PE,
	ON_DUTY;

	public String authority() {
		return "ROLE_" + name();
	}

	public static Optional<Role> fromString(String s) {
		if (s == null) return Optional.empty();
		return Arrays.stream(values())
				.filter(r -> r.name().equalsIgnoreCase(s.trim()))
				.findFirst();
	}
}
