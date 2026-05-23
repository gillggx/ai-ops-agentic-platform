/**
 * Pipeline HTTP layer + business services.
 *
 * <p>Layering (Phase 12 OOP refactor 2026-05-23):
 * <ul>
 *   <li>{@link com.aiops.api.api.pipeline.PipelineController} — thin HTTP
 *       wrapper around {@link com.aiops.api.api.pipeline.PipelineService}
 *       for the canonical {@code /api/v1/pipelines/*} surface.</li>
 *   <li>{@link com.aiops.api.api.pipeline.PipelineService} — CRUD +
 *       5-stage state machine (draft → validating → locked → active →
 *       archived) + structural {@code pipeline_json} validator + cross-
 *       entity writes (Pipeline + PublishedSkill + AutoCheckTrigger) +
 *       AutoCheck binding replace logic.</li>
 *   <li>{@link com.aiops.api.api.pipeline.PipelineBuilderController} +
 *       {@link com.aiops.api.api.pipeline.PipelineBuilderService} —
 *       legacy path-parity alias under {@code /api/v1/pipeline-builder/*};
 *       contains the block JSON-column unpacker + skill substring search
 *       + auto-check trigger join. Sidecar forwards stay in controller.</li>
 *   <li>{@link com.aiops.api.api.pipeline.PublishedSkillController} —
 *       read-side surface for the active published skill registry.</li>
 *   <li>{@link com.aiops.api.api.pipeline.PipelineDocGenerator} —
 *       auto-generates a publish-doc skeleton from pipeline_json + block
 *       metadata; consumed by {@code PipelineService.publishDraftDoc}.</li>
 *   <li>{@link com.aiops.api.api.pipeline.PipelineDtos} — HTTP DTOs
 *       (Summary / Detail / CreateRequest / UpdateRequest / etc.) lifted
 *       from nested static classes for shared use by controller +
 *       service.</li>
 * </ul>
 */
package com.aiops.api.api.pipeline;
