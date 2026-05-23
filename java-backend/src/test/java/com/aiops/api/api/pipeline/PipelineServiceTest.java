package com.aiops.api.api.pipeline;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.common.ApiException;
import com.aiops.api.domain.pipeline.PipelineAutoCheckTriggerRepository;
import com.aiops.api.domain.pipeline.PipelineEntity;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.pipeline.PipelineRunRepository;
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
import org.springframework.http.HttpStatus;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * Coverage for PipelineService — focus on the two areas with non-trivial
 * logic that are otherwise hard to exercise from integration: the 5-stage
 * state machine in {@code ALLOWED_TRANSITIONS} + the structural
 * pipeline_json validator. CRUD passthroughs aren't covered (the
 * controller-level smoke already exercises those end-to-end).
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class PipelineServiceTest {

	@Mock PipelineRepository repository;
	@Mock PublishedSkillRepository publishedSkillRepository;
	@Mock PipelineAutoCheckTriggerRepository autoCheckTriggerRepository;
	@Mock PipelineRunRepository pipelineRunRepository;
	@Mock PipelineDocGenerator docGenerator;
	@Mock AuthPrincipal caller;

	private ObjectMapper mapper;
	private PipelineService service;

	@BeforeEach
	void setup() {
		mapper = new ObjectMapper();
		service = new PipelineService(repository, publishedSkillRepository,
				autoCheckTriggerRepository, pipelineRunRepository, docGenerator, mapper);
	}

	// ── State machine ──────────────────────────────────────────────────────

	@Nested @DisplayName("transition state machine")
	class StateMachine {

		private PipelineEntity at(String status) {
			PipelineEntity e = new PipelineEntity();
			e.setId(1L);
			e.setStatus(status);
			when(repository.findById(1L)).thenReturn(Optional.of(e));
			when(repository.save(any())).thenAnswer(inv -> inv.getArgument(0));
			return e;
		}

		@Test
		void draftToValidating() {
			at("draft");
			assertThat(service.transition(1L, "validating").getStatus()).isEqualTo("validating");
		}

		@Test
		void draftToArchived() {
			at("draft");
			assertThat(service.transition(1L, "archived").getStatus()).isEqualTo("archived");
		}

		@Test
		void draftCannotJumpToLocked() {
			at("draft");
			assertThatThrownBy(() -> service.transition(1L, "locked"))
					.isInstanceOf(ApiException.class)
					.hasMessageContaining("Cannot transition from 'draft' to 'locked'");
		}

		@Test
		void validatingToLocked() {
			PipelineEntity e = at("validating");
			service.transition(1L, "locked");
			assertThat(e.getStatus()).isEqualTo("locked");
			assertThat(e.getLockedAt()).isNotNull();
		}

		@Test
		void validatingToDraft() {
			at("validating");
			assertThat(service.transition(1L, "draft").getStatus()).isEqualTo("draft");
		}

		@Test
		void lockedToActiveStampsPublishedAt() {
			PipelineEntity e = at("locked");
			service.transition(1L, "active");
			assertThat(e.getStatus()).isEqualTo("active");
			assertThat(e.getPublishedAt()).isNotNull();
		}

		@Test
		void lockedBackToDraftClearsLockedFields() {
			PipelineEntity e = at("locked");
			e.setLockedAt(java.time.OffsetDateTime.now());
			e.setLockedBy("admin");
			service.transition(1L, "draft");
			assertThat(e.getLockedAt()).isNull();
			assertThat(e.getLockedBy()).isNull();
		}

		@Test
		void activeToArchivedStampsArchivedAt() {
			PipelineEntity e = at("active");
			service.transition(1L, "archived");
			assertThat(e.getStatus()).isEqualTo("archived");
			assertThat(e.getArchivedAt()).isNotNull();
		}

		@Test
		void archivedIsTerminal() {
			at("archived");
			for (String to : new String[]{"draft", "validating", "locked", "active"}) {
				assertThatThrownBy(() -> service.transition(1L, to))
						.isInstanceOf(ApiException.class)
						.hasMessageContaining("Cannot transition from 'archived'");
			}
		}
	}

	// ── Structural validation (checkStructural via create) ─────────────────

	@Nested @DisplayName("checkStructural via create")
	class CheckStructural {

		private PipelineDtos.CreateRequest withJson(String pj) {
			return new PipelineDtos.CreateRequest("p1", null, null, pj, "0.1");
		}

		@Test
		void nullPipelineJsonAccepted() {
			when(repository.save(any())).thenAnswer(inv -> inv.getArgument(0));
			when(caller.userId()).thenReturn(7L);
			service.create(withJson(null), caller);  // no throw
		}

		@Test
		void malformedJsonRejected() {
			assertThatThrownBy(() -> service.create(withJson("{not json"), caller))
					.isInstanceOf(ApiException.class)
					.hasMessageContaining("pipeline_json is not valid JSON");
		}

		@Test
		void nodeMissingIdRejected() {
			String pj = "{\"nodes\":[{\"block_type\":\"x\"}],\"edges\":[]}";
			assertThatThrownBy(() -> service.create(withJson(pj), caller))
					.isInstanceOf(ApiException.class)
					.hasMessageContaining("pipeline node missing 'id'");
		}

		@Test
		void duplicateNodeIdRejected() {
			String pj = "{\"nodes\":[{\"id\":\"n1\"},{\"id\":\"n1\"}],\"edges\":[]}";
			assertThatThrownBy(() -> service.create(withJson(pj), caller))
					.isInstanceOf(ApiException.class)
					.hasMessageContaining("duplicate node id");
		}

		@Test
		void edgeMissingEndpointRejected() {
			String pj = "{\"nodes\":[{\"id\":\"n1\"}],\"edges\":[{\"from\":{\"node\":\"n1\"}}]}";
			assertThatThrownBy(() -> service.create(withJson(pj), caller))
					.isInstanceOf(ApiException.class)
					.hasMessageContaining("pipeline edge missing from/to endpoint");
		}

		@Test
		void edgeToUnknownNodeRejected() {
			String pj = "{\"nodes\":[{\"id\":\"n1\"}],\"edges\":["
					+ "{\"from\":{\"node\":\"n1\",\"port\":\"out\"},"
					+ "\"to\":{\"node\":\"missing\",\"port\":\"in\"}}]}";
			assertThatThrownBy(() -> service.create(withJson(pj), caller))
					.isInstanceOf(ApiException.class)
					.hasMessageContaining("references unknown destination node 'missing'");
		}

		@Test
		void edgeFromUnknownNodeRejected() {
			String pj = "{\"nodes\":[{\"id\":\"n1\"}],\"edges\":["
					+ "{\"from\":{\"node\":\"ghost\",\"port\":\"out\"},"
					+ "\"to\":{\"node\":\"n1\",\"port\":\"in\"}}]}";
			assertThatThrownBy(() -> service.create(withJson(pj), caller))
					.isInstanceOf(ApiException.class)
					.hasMessageContaining("references unknown source node 'ghost'");
		}

		@Test
		void validPipelineAccepted() {
			when(repository.save(any())).thenAnswer(inv -> inv.getArgument(0));
			when(caller.userId()).thenReturn(7L);
			String pj = "{\"nodes\":[{\"id\":\"a\"},{\"id\":\"b\"}],"
					+ "\"edges\":[{\"from\":{\"node\":\"a\",\"port\":\"out\"},"
					+ "\"to\":{\"node\":\"b\",\"port\":\"in\"}}]}";
			service.create(withJson(pj), caller);  // no throw
		}
	}

	// ── update() — locked/archived guard ───────────────────────────────────

	@Nested @DisplayName("update guards")
	class UpdateGuards {

		@Test
		void lockedPipelineCannotBeMutated() {
			PipelineEntity e = new PipelineEntity();
			e.setStatus("locked");
			when(repository.findById(1L)).thenReturn(Optional.of(e));
			PipelineDtos.UpdateRequest req = new PipelineDtos.UpdateRequest(
					"new name", null, null, null, null);
			assertThatThrownBy(() -> service.update(1L, req))
					.isInstanceOf(ApiException.class)
					.hasMessageContaining("pipeline is locked");
		}

		@Test
		void archivedPipelineCannotBeMutated() {
			PipelineEntity e = new PipelineEntity();
			e.setStatus("archived");
			when(repository.findById(1L)).thenReturn(Optional.of(e));
			PipelineDtos.UpdateRequest req = new PipelineDtos.UpdateRequest(
					"new name", null, null, null, null);
			assertThatThrownBy(() -> service.update(1L, req))
					.isInstanceOf(ApiException.class)
					.hasMessageContaining("pipeline is archived");
		}
	}

	// ── fork() — draft refusal + metadata stamp ────────────────────────────

	@Nested @DisplayName("fork")
	class Fork {

		@Test
		void draftRejected() {
			PipelineEntity src = new PipelineEntity();
			src.setStatus("draft");
			when(repository.findById(1L)).thenReturn(Optional.of(src));
			assertThatThrownBy(() -> service.fork(1L, caller))
					.isInstanceOf(ApiException.class)
					.hasMessageContaining("Cannot clone a draft");
		}

		@Test
		void clonedPipelineGetsParentIdAndMetadata() throws Exception {
			PipelineEntity src = new PipelineEntity();
			src.setId(5L);
			src.setStatus("active");
			src.setName("Original");
			src.setPipelineJson("{\"nodes\":[],\"edges\":[]}");
			src.setVersion("1.0");
			when(repository.findById(5L)).thenReturn(Optional.of(src));
			when(repository.save(any())).thenAnswer(inv -> inv.getArgument(0));
			when(caller.userId()).thenReturn(99L);

			PipelineEntity forked = service.fork(5L, caller);

			assertThat(forked.getStatus()).isEqualTo("draft");
			assertThat(forked.getParentId()).isEqualTo(5L);
			assertThat(forked.getName()).isEqualTo("Original (clone)");
			assertThat(forked.getCreatedBy()).isEqualTo(99L);
			// metadata.fork_of stamped
			com.fasterxml.jackson.databind.JsonNode root = mapper.readTree(forked.getPipelineJson());
			assertThat(root.path("metadata").path("fork_of").asLong()).isEqualTo(5L);
		}
	}

	// ── publish() refusals ─────────────────────────────────────────────────

	@Nested @DisplayName("publish guards")
	class PublishGuards {

		@Test
		void mustBeLocked() {
			PipelineEntity e = new PipelineEntity();
			e.setStatus("draft");
			when(repository.findById(1L)).thenReturn(Optional.of(e));
			PipelineDtos.PublishRequest req = new PipelineDtos.PublishRequest(java.util.Map.of(), "admin");
			assertThatThrownBy(() -> service.publish(1L, req))
					.isInstanceOf(ApiException.class)
					.hasMessageContaining("Pipeline must be 'locked'");
		}

		@Test
		void rejectsNonSkillKind() {
			PipelineEntity e = new PipelineEntity();
			e.setStatus("locked");
			e.setPipelineKind("auto_check");
			when(repository.findById(1L)).thenReturn(Optional.of(e));
			PipelineDtos.PublishRequest req = new PipelineDtos.PublishRequest(java.util.Map.of(), "admin");
			assertThatThrownBy(() -> service.publish(1L, req))
					.isInstanceOf(ApiException.class)
					.hasMessageContaining("Only skill pipelines");
		}

		@Test
		void rejectsMissingReviewedDocFields() {
			PipelineEntity e = new PipelineEntity();
			e.setStatus("locked");
			e.setPipelineKind("skill");
			when(repository.findById(1L)).thenReturn(Optional.of(e));
			PipelineDtos.PublishRequest req = new PipelineDtos.PublishRequest(
					java.util.Map.of("slug", "x"), "admin");
			assertThatThrownBy(() -> service.publish(1L, req))
					.isInstanceOf(ApiException.class)
					.satisfies(ex -> assertThat(((ApiException) ex).status())
							.isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY))
					.hasMessageContaining("missing fields");
		}
	}
}
