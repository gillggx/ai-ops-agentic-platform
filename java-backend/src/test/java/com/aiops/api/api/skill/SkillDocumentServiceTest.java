package com.aiops.api.api.skill;

import com.aiops.api.auth.AuthPrincipal;
import com.aiops.api.common.ApiException;
import com.aiops.api.domain.alarm.AlarmRepository;
import com.aiops.api.domain.event.EventTypeRepository;
import com.aiops.api.domain.pipeline.PipelineRepository;
import com.aiops.api.domain.skill.SkillDocumentEntity;
import com.aiops.api.domain.skill.SkillDocumentRepository;
import com.aiops.api.domain.skill.SkillRunRepository;
import com.aiops.api.sidecar.PythonSidecarClient;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.HttpStatus;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Coverage for the SkillDocumentService business rules: stage / priority
 * validation, slug auto-generation, stage auto-flip from trigger.type,
 * and CRUD happy/404 paths. Pure Mockito — no Spring context.
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class SkillDocumentServiceTest {

	@Mock SkillDocumentRepository repository;
	@Mock SkillRunRepository runRepository;
	@Mock AlarmRepository alarmRepo;
	@Mock PipelineRepository pipelineRepo;
	@Mock EventTypeRepository eventTypeRepo;
	@Mock SkillMaterializeService materializer;
	@Mock PythonSidecarClient sidecar;
	@Mock AuthPrincipal caller;

	private ObjectMapper mapper;
	private SkillDocumentService service;

	@BeforeEach
	void setup() {
		mapper = new ObjectMapper();
		service = new SkillDocumentService(repository, runRepository, mapper,
				alarmRepo, pipelineRepo, eventTypeRepo, materializer, sidecar);
		when(caller.userId()).thenReturn(42L);
	}

	// ── autoSlug (static helper, no service needed) ────────────────────────

	@Nested @DisplayName("autoSlug")
	class AutoSlug {

		@Test
		void asciiLowercasedAndDashed() {
			String slug = SkillDocumentService.autoSlug("My SPC OOC Watch");
			assertThat(slug).startsWith("my-spc-ooc-watch-");
		}

		@Test
		void cjkOnlyFallsBackToSkillPrefix() {
			String slug = SkillDocumentService.autoSlug("巡檢規則");
			assertThat(slug).startsWith("skill-");
		}

		@Test
		void nullTitleReturnsSkillPrefix() {
			String slug = SkillDocumentService.autoSlug(null);
			assertThat(slug).startsWith("skill-");
		}

		@Test
		void cappedAt60CharsTotal() {
			String slug = SkillDocumentService.autoSlug("a".repeat(100));
			// 40 char base + "-" + base36 epoch (8-10 chars) ≤ 60
			assertThat(slug.length()).isLessThanOrEqualTo(60);
		}

		@Test
		void stripsPunctuation() {
			String slug = SkillDocumentService.autoSlug("Foo, Bar! Baz?");
			assertThat(slug).startsWith("foo-bar-baz-");
		}
	}

	// ── stageFromTrigger ───────────────────────────────────────────────────

	@Nested @DisplayName("stageFromTrigger")
	class StageFromTrigger {

		@Test
		void scheduleMapsToPatrol() {
			assertThat(service.stageFromTrigger("{\"type\":\"schedule\"}")).isEqualTo("patrol");
		}

		@Test
		void eventMapsToDiagnose() {
			assertThat(service.stageFromTrigger("{\"type\":\"event\",\"event\":\"OOC\"}"))
					.isEqualTo("diagnose");
		}

		@Test
		void legacySystemMapsToDiagnose() {
			assertThat(service.stageFromTrigger("{\"type\":\"system\"}")).isEqualTo("diagnose");
		}

		@Test
		void nullReturnsNull() {
			assertThat(service.stageFromTrigger(null)).isNull();
			assertThat(service.stageFromTrigger("")).isNull();
		}

		@Test
		void unknownTypeReturnsNull() {
			assertThat(service.stageFromTrigger("{\"type\":\"manual\"}")).isNull();
		}

		@Test
		void malformedJsonReturnsNull() {
			assertThat(service.stageFromTrigger("{not json")).isNull();
		}
	}

	// ── create() validation ────────────────────────────────────────────────

	@Nested @DisplayName("create")
	class Create {

		@Test
		void invalidStageRejected() {
			Dtos.CreateRequest req = new Dtos.CreateRequest(
					"slug-x", "title", "BAD_STAGE", null, null, null, null, null);
			assertThatThrownBy(() -> service.create(req, caller))
					.isInstanceOf(ApiException.class)
					.hasMessageContaining("stage must be patrol|diagnose");
		}

		@Test
		void duplicateSlugRejected() {
			when(repository.existsBySlug("dup")).thenReturn(true);
			Dtos.CreateRequest req = new Dtos.CreateRequest(
					"dup", "title", null, null, null, null, null, null);
			assertThatThrownBy(() -> service.create(req, caller))
					.isInstanceOf(ApiException.class)
					.hasMessageContaining("slug already exists: dup");
		}

		@Test
		void omittedStageDefaultsToDiagnose() {
			when(repository.save(any(SkillDocumentEntity.class)))
					.thenAnswer(inv -> inv.getArgument(0));
			Dtos.CreateRequest req = new Dtos.CreateRequest(
					"explicit-slug", "title", null, null, null, null, null, null);
			SkillDocumentEntity saved = service.create(req, caller);
			assertThat(saved.getStage()).isEqualTo("diagnose");
		}

		@Test
		void omittedSlugIsAutoGenerated() {
			ArgumentCaptor<SkillDocumentEntity> cap = ArgumentCaptor.forClass(SkillDocumentEntity.class);
			when(repository.save(cap.capture())).thenAnswer(inv -> inv.getArgument(0));
			Dtos.CreateRequest req = new Dtos.CreateRequest(
					null, "My Watch Rule", null, null, null, null, null, null);
			service.create(req, caller);
			assertThat(cap.getValue().getSlug()).startsWith("my-watch-rule-");
		}

		@Test
		void omittedFieldsGetSafeDefaults() {
			ArgumentCaptor<SkillDocumentEntity> cap = ArgumentCaptor.forClass(SkillDocumentEntity.class);
			when(repository.save(cap.capture())).thenAnswer(inv -> inv.getArgument(0));
			Dtos.CreateRequest req = new Dtos.CreateRequest(
					"slug", "title", null, null, null, null, null, null);
			service.create(req, caller);
			SkillDocumentEntity e = cap.getValue();
			assertThat(e.getDomain()).isEqualTo("");
			assertThat(e.getDescription()).isEqualTo("");
			assertThat(e.getVersion()).isEqualTo("0.1");
			assertThat(e.getStatus()).isEqualTo("draft");
			assertThat(e.getTriggerConfig()).isEqualTo("{}");
			assertThat(e.getSteps()).isEqualTo("[]");
			assertThat(e.getAuthorUserId()).isEqualTo(42L);
		}
	}

	// ── update() — stage auto-flip + materializer side effects ─────────────

	@Nested @DisplayName("update")
	class Update {

		private SkillDocumentEntity existingDraftEvent() {
			SkillDocumentEntity e = new SkillDocumentEntity();
			e.setSlug("s");
			e.setStage("diagnose");
			e.setStatus("draft");
			e.setTriggerConfig("{\"type\":\"event\"}");
			return e;
		}

		@Test
		void unknownSlugThrows404() {
			when(repository.findBySlug("nope")).thenReturn(Optional.empty());
			Dtos.UpdateRequest req = new Dtos.UpdateRequest(
					null, null, null, null, null, null, null, null, null, null);
			assertThatThrownBy(() -> service.update("nope", req))
					.isInstanceOf(ApiException.class);
		}

		@Test
		void triggerScheduleAutoFlipsStageToPatrol() {
			SkillDocumentEntity e = existingDraftEvent();
			when(repository.findBySlug("s")).thenReturn(Optional.of(e));
			Dtos.UpdateRequest req = new Dtos.UpdateRequest(
					null, null, null, null, null, null, null,
					"{\"type\":\"schedule\",\"cron\":\"0 * * * *\"}", null, null);
			service.update("s", req);
			assertThat(e.getStage()).isEqualTo("patrol");
		}

		@Test
		void explicitStageNotOverridenByTrigger() {
			SkillDocumentEntity e = existingDraftEvent();
			when(repository.findBySlug("s")).thenReturn(Optional.of(e));
			Dtos.UpdateRequest req = new Dtos.UpdateRequest(
					null, "diagnose", null, null, null, null, null,
					"{\"type\":\"schedule\"}", null, null);
			service.update("s", req);
			// Explicit stage wins
			assertThat(e.getStage()).isEqualTo("diagnose");
		}

		@Test
		void invalidStatusRejected() {
			when(repository.findBySlug("s")).thenReturn(Optional.of(existingDraftEvent()));
			Dtos.UpdateRequest req = new Dtos.UpdateRequest(
					null, null, "QUARANTINED", null, null, null, null, null, null, null);
			assertThatThrownBy(() -> service.update("s", req))
					.isInstanceOf(ApiException.class)
					.hasMessageContaining("status must be draft|stable");
		}

		@Test
		void draftToStableTriggersMaterialize() {
			SkillDocumentEntity e = existingDraftEvent();
			when(repository.findBySlug("s")).thenReturn(Optional.of(e));
			when(materializer.materialize(any())).thenReturn(3);
			Dtos.UpdateRequest req = new Dtos.UpdateRequest(
					null, null, "stable", null, null, null, null, null, null, null);
			service.update("s", req);
			verify(materializer).materialize(e);
			verify(materializer, never()).clear(any());
		}

		@Test
		void stableToDraftTriggersClear() {
			SkillDocumentEntity e = existingDraftEvent();
			e.setStatus("stable");
			when(repository.findBySlug("s")).thenReturn(Optional.of(e));
			when(materializer.clear(any())).thenReturn(2);
			Dtos.UpdateRequest req = new Dtos.UpdateRequest(
					null, null, "draft", null, null, null, null, null, null, null);
			service.update("s", req);
			verify(materializer).clear(e);
			verify(materializer, never()).materialize(any());
		}

		@Test
		void confirmCheckBlankClears() {
			SkillDocumentEntity e = existingDraftEvent();
			e.setConfirmCheck("{\"existing\":\"value\"}");
			when(repository.findBySlug("s")).thenReturn(Optional.of(e));
			Dtos.UpdateRequest req = new Dtos.UpdateRequest(
					null, null, null, null, null, null, null, null, null, "");
			service.update("s", req);
			assertThat(e.getConfirmCheck()).isNull();
		}
	}

	// ── delete() ───────────────────────────────────────────────────────────

	@Nested @DisplayName("delete")
	class Delete {

		@Test
		void unknownSlugThrows404() {
			when(repository.findBySlug("nope")).thenReturn(Optional.empty());
			assertThatThrownBy(() -> service.delete("nope"))
					.isInstanceOf(ApiException.class);
		}

		@Test
		void clearsMaterializedRowsBeforeDelete() {
			SkillDocumentEntity e = new SkillDocumentEntity();
			when(repository.findBySlug("s")).thenReturn(Optional.of(e));
			service.delete("s");
			verify(materializer).clear(e);
			verify(repository).delete(e);
		}
	}

	// ── list() / getBySlug() ───────────────────────────────────────────────

	@Nested @DisplayName("read paths")
	class Reads {

		@Test
		void listWithBlankStageReturnsAll() {
			when(repository.findAll()).thenReturn(java.util.List.of());
			service.list(null);
			service.list("");
			service.list("  ");
			verify(repository, org.mockito.Mockito.times(3)).findAll();
			verify(repository, never()).findByStage(any());
		}

		@Test
		void listWithStageFilters() {
			service.list("patrol");
			verify(repository).findByStage("patrol");
		}

		@Test
		void getBySlugUnknownThrows404() {
			when(repository.findBySlug("nope")).thenReturn(Optional.empty());
			assertThatThrownBy(() -> service.getBySlug("nope"))
					.isInstanceOf(ApiException.class)
					.satisfies(ex -> assertThat(((ApiException) ex).status())
							.isEqualTo(HttpStatus.NOT_FOUND));
		}
	}
}
