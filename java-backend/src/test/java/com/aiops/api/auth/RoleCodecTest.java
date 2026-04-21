package com.aiops.api.auth;

import org.junit.jupiter.api.Test;

import java.util.EnumSet;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

class RoleCodecTest {

	private final RoleCodec codec = new RoleCodec();

	@Test
	void encodeEmptyReturnsEmptyJsonArray() {
		assertThat(codec.encode(Set.of())).isEqualTo("[]");
	}

	@Test
	void roundTripSingleRole() {
		String json = codec.encode(EnumSet.of(Role.PE));
		assertThat(json).isEqualTo("[\"PE\"]");
		assertThat(codec.decode(json)).containsExactly(Role.PE);
	}

	@Test
	void roundTripMultipleRolesSorted() {
		// Order-independent: codec writes sorted form
		String json = codec.encode(EnumSet.of(Role.ON_DUTY, Role.IT_ADMIN));
		assertThat(json).contains("IT_ADMIN").contains("ON_DUTY");
		assertThat(codec.decode(json)).containsExactlyInAnyOrder(Role.IT_ADMIN, Role.ON_DUTY);
	}

	@Test
	void decodeInvalidJsonReturnsEmpty() {
		assertThat(codec.decode("not-json")).isEmpty();
		assertThat(codec.decode(null)).isEmpty();
		assertThat(codec.decode("")).isEmpty();
	}

	@Test
	void decodeIgnoresUnknownRoleNames() {
		assertThat(codec.decode("[\"PE\",\"unknown_role\"]")).containsExactly(Role.PE);
	}
}
