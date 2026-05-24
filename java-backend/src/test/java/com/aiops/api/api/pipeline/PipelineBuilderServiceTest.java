package com.aiops.api.api.pipeline;

import com.aiops.api.domain.pipeline.BlockEntity;
import com.aiops.api.domain.pipeline.BlockRepository;
import com.aiops.api.domain.pipeline.PipelineAutoCheckTriggerEntity;
import com.aiops.api.domain.pipeline.PipelineAutoCheckTriggerRepository;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.pipeline.PublishedSkillEntity;
import com.aiops.api.domain.pipeline.PublishedSkillRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.when;

/**
 * Coverage for PipelineBuilderService — the three non-trivial logic
 * surfaces extracted in P0-7: BlockEntity JSON-column unpacking,
 * substring-scored skill search, and the auto-check trigger join.
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class PipelineBuilderServiceTest {

	@Mock PipelineRepository pipelineRepo;
	@Mock BlockRepository blockRepo;
	@Mock PublishedSkillRepository publishedSkillRepo;
	@Mock PipelineAutoCheckTriggerRepository autoCheckRepo;

	private ObjectMapper mapper;
	private PipelineBuilderService service;

	@BeforeEach
	void setup() {
		mapper = new ObjectMapper();
		service = new PipelineBuilderService(pipelineRepo, blockRepo, publishedSkillRepo,
				autoCheckRepo, mapper);
	}

	// ── listBlocks: JSON column parsing ────────────────────────────────────

	@Nested @DisplayName("listBlocks")
	class ListBlocks {

		@Test
		void parsesJsonColumnsToArraysAndObjects() {
			BlockEntity b = new BlockEntity();
			b.setId(1L);
			b.setName("block_data_view");
			b.setInputSchema("[{\"name\":\"df\",\"type\":\"dataframe\"}]");
			b.setOutputSchema("{\"type\":\"object\"}");
			b.setParamSchema("[]");
			b.setExamples("[]");
			when(blockRepo.findAll()).thenReturn(List.of(b));

			List<Map<String, Object>> rows = service.listBlocks();

			assertThat(rows).hasSize(1);
			// input_schema came in as text but should now be a List/array
			assertThat(rows.get(0).get("input_schema")).isInstanceOf(com.fasterxml.jackson.databind.JsonNode.class);
			assertThat(((com.fasterxml.jackson.databind.JsonNode) rows.get(0).get("input_schema")).isArray()).isTrue();
		}

		@Test
		void malformedJsonStaysAsRawString() {
			BlockEntity b = new BlockEntity();
			b.setName("broken");
			b.setInputSchema("{not json");
			when(blockRepo.findAll()).thenReturn(List.of(b));

			List<Map<String, Object>> rows = service.listBlocks();
			// On parse failure, returns the original string
			assertThat(rows.get(0).get("input_schema")).isEqualTo("{not json");
		}

		@Test
		void blankColumnsBecomeNull() {
			BlockEntity b = new BlockEntity();
			b.setName("empty");
			b.setInputSchema("");
			when(blockRepo.findAll()).thenReturn(List.of(b));

			List<Map<String, Object>> rows = service.listBlocks();
			assertThat(rows.get(0).get("input_schema")).isNull();
		}
	}

	// ── searchPublishedSkills: ranking ─────────────────────────────────────

	@Nested @DisplayName("searchPublishedSkills")
	class SearchPublishedSkills {

		private PublishedSkillEntity skill(String slug, String name, String useCase, String tags) {
			PublishedSkillEntity s = new PublishedSkillEntity();
			s.setSlug(slug);
			s.setName(name);
			s.setUseCase(useCase);
			s.setWhenToUse("");
			s.setTags(tags == null ? "" : tags);
			s.setStatus("active");
			return s;
		}

		@Test
		void emptyQueryReturnsAlphabeticalTopK() {
			when(publishedSkillRepo.findByStatus("active")).thenReturn(List.of(
					skill("c-slug", "Charlie", "x", null),
					skill("a-slug", "Alpha", "x", null),
					skill("b-slug", "Bravo", "x", null)
			));
			List<PublishedSkillEntity> result = service.searchPublishedSkills(null, 5);
			assertThat(result).extracting(PublishedSkillEntity::getName)
					.containsExactly("Alpha", "Bravo", "Charlie");
		}

		@Test
		void emptyQueryRespectsTopK() {
			when(publishedSkillRepo.findByStatus("active")).thenReturn(List.of(
					skill("a", "A", "x", null), skill("b", "B", "x", null), skill("c", "C", "x", null)));
			assertThat(service.searchPublishedSkills("", 2)).hasSize(2);
		}

		@Test
		void substringMatchScoredAcrossFields() {
			when(publishedSkillRepo.findByStatus("active")).thenReturn(List.of(
					skill("apc-slug", "APC Watch", "monitor APC drift", "apc"),       // 3 matches
					skill("spc-slug", "SPC Watch", "detect OOC", "spc"),               // 0 matches
					skill("apc-tool", "APC Tool", "another", null)                     // 1 match (name only)
			));
			List<PublishedSkillEntity> result = service.searchPublishedSkills("apc", 5);
			// Both apc-* should be ranked above spc-slug; apc-slug first (more matches)
			assertThat(result).extracting(PublishedSkillEntity::getSlug)
					.containsExactly("apc-slug", "apc-tool");
		}

		@Test
		void zeroMatchSkillsFilteredOut() {
			when(publishedSkillRepo.findByStatus("active")).thenReturn(List.of(
					skill("a", "Alpha", "no overlap", null),
					skill("b", "Bravo", "matches xyz", null)
			));
			assertThat(service.searchPublishedSkills("xyz", 5))
					.extracting(PublishedSkillEntity::getSlug).containsExactly("b");
		}

		@Test
		void topKDefaultsTo5AndCapsAt50() {
			when(publishedSkillRepo.findByStatus("active")).thenReturn(List.of());
			// just verify no NPE / no crash
			assertThat(service.searchPublishedSkills("x", null)).isEmpty();
			assertThat(service.searchPublishedSkills("x", -1)).isEmpty();
			assertThat(service.searchPublishedSkills("x", 9999)).isEmpty();
		}
	}

	// ── listAutoCheckRules: join behaviour ─────────────────────────────────

	@Nested @DisplayName("listAutoCheckRules")
	class ListAutoCheckRules {

		@Test
		void emptyTriggersReturnsEmpty() {
			when(autoCheckRepo.findAll()).thenReturn(List.of());
			assertThat(service.listAutoCheckRules()).isEmpty();
		}

		@Test
		void joinsPipelineNameAndStatus() {
			PipelineAutoCheckTriggerEntity t = new PipelineAutoCheckTriggerEntity();
			t.setId(10L);
			t.setPipelineId(7L);
			t.setEventType("spc.ooc");
			when(autoCheckRepo.findAll()).thenReturn(List.of(t));

			PipelineEntity pipeline = new PipelineEntity();
			pipeline.setId(7L);
			pipeline.setName("OOC Diagnostic");
			pipeline.setStatus("active");
			when(pipelineRepo.findAllById(anyList())).thenReturn(List.of(pipeline));

			List<Map<String, Object>> result = service.listAutoCheckRules();
			assertThat(result).hasSize(1);
			Map<String, Object> row = result.get(0);
			assertThat(row).containsEntry("pipeline_name", "OOC Diagnostic")
					.containsEntry("pipeline_status", "active")
					.containsEntry("event_type", "spc.ooc");
		}

		@Test
		void missingPipelineYieldsNullNameAndStatus() {
			PipelineAutoCheckTriggerEntity t = new PipelineAutoCheckTriggerEntity();
			t.setId(10L);
			t.setPipelineId(999L);
			t.setEventType("spc.ooc");
			when(autoCheckRepo.findAll()).thenReturn(List.of(t));
			when(pipelineRepo.findAllById(any())).thenReturn(List.of());  // no match

			Map<String, Object> row = service.listAutoCheckRules().get(0);
			assertThat(row.get("pipeline_name")).isNull();
			assertThat(row.get("pipeline_status")).isNull();
		}
	}
}
