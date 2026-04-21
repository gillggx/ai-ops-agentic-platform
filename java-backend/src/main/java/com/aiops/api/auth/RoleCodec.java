package com.aiops.api.auth;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Component;

import java.util.*;

/**
 * JSON codec for the {@code users.roles} TEXT column.
 *
 * <p>The Python schema stores roles as a JSON array of strings (e.g. {@code ["PE","IT_ADMIN"]}).
 * This codec keeps Java ↔ DB compatible with that format.
 */
@Component
public class RoleCodec {

	private static final ObjectMapper MAPPER = new ObjectMapper();
	private static final TypeReference<List<String>> LIST_TYPE = new TypeReference<>() {};

	public Set<Role> decode(String json) {
		if (json == null || json.isBlank()) return Collections.emptySet();
		try {
			List<String> raw = MAPPER.readValue(json, LIST_TYPE);
			Set<Role> roles = EnumSet.noneOf(Role.class);
			for (String s : raw) {
				Role.fromString(s).ifPresent(roles::add);
			}
			return roles;
		} catch (Exception e) {
			return Collections.emptySet();
		}
	}

	public String encode(Set<Role> roles) {
		List<String> list = roles.stream().map(Role::name).sorted().toList();
		try {
			return MAPPER.writeValueAsString(list);
		} catch (Exception e) {
			return "[]";
		}
	}
}
