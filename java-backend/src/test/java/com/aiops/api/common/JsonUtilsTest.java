package com.aiops.api.common;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Coverage for the centralised JSON helper introduced in P2.
 *
 * <p>Pure helper, no Spring context — each test instantiates a fresh
 * ObjectMapper. Four method × four canonical input shapes (null / blank /
 * malformed / happy) is the matrix.
 */
class JsonUtilsTest {

	private ObjectMapper mapper;

	@BeforeEach
	void setup() {
		mapper = new ObjectMapper();
	}

	@Nested @DisplayName("parseObject")
	class ParseObject {

		@Test
		void nullReturnsEmpty() {
			assertThat(JsonUtils.parseObject(mapper, null)).isEmpty();
		}

		@Test
		void blankReturnsEmpty() {
			assertThat(JsonUtils.parseObject(mapper, "")).isEmpty();
			assertThat(JsonUtils.parseObject(mapper, "   ")).isEmpty();
		}

		@Test
		void malformedJsonReturnsEmpty() {
			assertThat(JsonUtils.parseObject(mapper, "{not json")).isEmpty();
			assertThat(JsonUtils.parseObject(mapper, "[]")).isEmpty();  // array, not object → parse fails as Map
		}

		@Test
		void happyPathReturnsParsedMap() {
			Map<String, Object> result = JsonUtils.parseObject(mapper,
					"{\"a\":1,\"b\":\"two\",\"c\":true}");
			assertThat(result).containsEntry("a", 1)
					.containsEntry("b", "two")
					.containsEntry("c", true);
		}

		@Test
		void nestedObjectsPreserved() {
			Map<String, Object> result = JsonUtils.parseObject(mapper,
					"{\"outer\":{\"inner\":\"value\"}}");
			assertThat(result.get("outer")).isInstanceOf(Map.class);
		}
	}

	@Nested @DisplayName("parseListOfObjects")
	class ParseListOfObjects {

		@Test
		void nullReturnsEmpty() {
			assertThat(JsonUtils.parseListOfObjects(mapper, null)).isEmpty();
		}

		@Test
		void blankReturnsEmpty() {
			assertThat(JsonUtils.parseListOfObjects(mapper, "")).isEmpty();
		}

		@Test
		void malformedJsonReturnsEmpty() {
			assertThat(JsonUtils.parseListOfObjects(mapper, "[{broken")).isEmpty();
		}

		@Test
		void emptyArrayReturnsEmpty() {
			assertThat(JsonUtils.parseListOfObjects(mapper, "[]")).isEmpty();
		}

		@Test
		void happyPathReturnsParsedList() {
			List<Map<String, Object>> result = JsonUtils.parseListOfObjects(mapper,
					"[{\"id\":\"a\"},{\"id\":\"b\"}]");
			assertThat(result).hasSize(2);
			assertThat(result.get(0)).containsEntry("id", "a");
			assertThat(result.get(1)).containsEntry("id", "b");
		}
	}

	@Nested @DisplayName("safeWrite")
	class SafeWrite {

		@Test
		void nullObjectReturnsNull() {
			assertThat(JsonUtils.safeWrite(mapper, null)).isNull();
		}

		@Test
		void mapSerialisesToJson() {
			String json = JsonUtils.safeWrite(mapper, Map.of("k", "v"));
			assertThat(json).contains("\"k\"").contains("\"v\"");
		}

		@Test
		void listSerialisesToJson() {
			String json = JsonUtils.safeWrite(mapper, List.of(1, 2, 3));
			assertThat(json).isEqualTo("[1,2,3]");
		}

		@Test
		void primitiveSerialises() {
			assertThat(JsonUtils.safeWrite(mapper, 42)).isEqualTo("42");
			assertThat(JsonUtils.safeWrite(mapper, "hello")).isEqualTo("\"hello\"");
		}
	}

	@Nested @DisplayName("asMap")
	class AsMap {

		@Test
		void nullReturnsEmpty() {
			assertThat(JsonUtils.asMap(null)).isEmpty();
		}

		@Test
		void nonMapReturnsEmpty() {
			assertThat(JsonUtils.asMap("a string")).isEmpty();
			assertThat(JsonUtils.asMap(List.of("not a map"))).isEmpty();
			assertThat(JsonUtils.asMap(42)).isEmpty();
		}

		@Test
		void mapIsCastWithoutCopy() {
			Map<String, Object> input = Map.of("a", 1, "b", "two");
			Map<String, Object> result = JsonUtils.asMap(input);
			assertThat(result).containsEntry("a", 1).containsEntry("b", "two");
			// Same reference — no defensive copy (caller copies if needed)
			assertThat(result).isSameAs(input);
		}
	}
}
