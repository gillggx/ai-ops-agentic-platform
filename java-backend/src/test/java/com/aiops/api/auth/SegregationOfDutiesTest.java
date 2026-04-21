package com.aiops.api.auth;

import com.aiops.api.common.ApiException;
import org.junit.jupiter.api.Test;

import java.util.EnumSet;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SegregationOfDutiesTest {

	@Test
	void emptyRolesRejected() {
		assertThatThrownBy(() -> SegregationOfDuties.validate(EnumSet.noneOf(Role.class)))
				.isInstanceOf(ApiException.class);
	}

	@Test
	void itAdminPlusPeRejected() {
		assertThatThrownBy(() -> SegregationOfDuties.validate(EnumSet.of(Role.IT_ADMIN, Role.PE)))
				.isInstanceOf(ApiException.class);
	}

	@Test
	void onDutyMustBeSolo() {
		assertThatThrownBy(() -> SegregationOfDuties.validate(EnumSet.of(Role.ON_DUTY, Role.PE)))
				.isInstanceOf(ApiException.class);
	}

	@Test
	void singleItAdminOk() {
		assertThatCode(() -> SegregationOfDuties.validate(EnumSet.of(Role.IT_ADMIN)))
				.doesNotThrowAnyException();
	}

	@Test
	void singlePeOk() {
		assertThatCode(() -> SegregationOfDuties.validate(EnumSet.of(Role.PE)))
				.doesNotThrowAnyException();
	}

	@Test
	void soloOnDutyOk() {
		assertThatCode(() -> SegregationOfDuties.validate(EnumSet.of(Role.ON_DUTY)))
				.doesNotThrowAnyException();
	}
}
