package com.aiops.api.api.alarm;

import com.aiops.api.domain.alarm.AlarmEntity;

import java.time.OffsetDateTime;
import java.util.List;

public final class AlarmDtos {

	private AlarmDtos() {}

	public record Summary(Long id, Long skillId, String triggerEvent, String equipmentId,
	                      String lotId, String step, String severity, String status, String title,
	                      String summary, OffsetDateTime eventTime, OffsetDateTime createdAt,
	                      String acknowledgedBy, OffsetDateTime acknowledgedAt,
	                      OffsetDateTime resolvedAt, Long executionLogId, Long diagnosticLogId,
	                      Object findings, Object outputSchema,
	                      Object diagnosticFindings, Object diagnosticOutputSchema,
	                      List<Object> charts,
	                      List<DiagnosticResult> diagnosticResults,
	                      List<DataView> triggerDataViews, List<DataView> diagnosticDataViews,
	                      List<Object> diagnosticCharts, Object diagnosticAlert) {}

	public record Detail(Long id, Long skillId, String triggerEvent, String equipmentId,
	                     String lotId, String step, OffsetDateTime eventTime,
	                     String severity, String title, String summary, String status,
	                     String acknowledgedBy, OffsetDateTime acknowledgedAt,
	                     OffsetDateTime resolvedAt, Long executionLogId, Long diagnosticLogId,
	                     OffsetDateTime createdAt,
	                     Object findings, Object outputSchema,
	                     Object diagnosticFindings, Object diagnosticOutputSchema,
	                     List<Object> charts,
	                     List<DiagnosticResult> diagnosticResults,
	                     List<DataView> triggerDataViews, List<DataView> diagnosticDataViews,
	                     List<Object> diagnosticCharts, Object diagnosticAlert) {}

	/** Direct view of a pipeline data_view node output (table). The pipeline
	 *  may emit multiple; ordered as block_data_view's `sequence` param. */
	public record DataView(String title, String description, List<String> columns,
	                       List<Object> rows, Integer totalRows) {}

	// NOTE: field names match the Python shape — log_id (not execution_log_id).
	public record DiagnosticResult(Long log_id, Long skill_id, String skill_name,
	                               String status, Object findings, Object output_schema,
	                               List<Object> charts) {}

	static Summary summaryOf(AlarmEntity e) {
		return new Summary(e.getId(), e.getSkillId(), e.getTriggerEvent(), e.getEquipmentId(),
				e.getLotId(), e.getStep(), e.getSeverity(), e.getStatus(), e.getTitle(),
				e.getSummary(), e.getEventTime(), e.getCreatedAt(),
				e.getAcknowledgedBy(), e.getAcknowledgedAt(), e.getResolvedAt(),
				e.getExecutionLogId(), e.getDiagnosticLogId(),
				null, null, null, null, List.of(), List.of(),
				List.of(), List.of(), List.of(), null);
	}

	static Detail detailOf(AlarmEntity e) {
		return new Detail(e.getId(), e.getSkillId(), e.getTriggerEvent(), e.getEquipmentId(),
				e.getLotId(), e.getStep(), e.getEventTime(), e.getSeverity(),
				e.getTitle(), e.getSummary(), e.getStatus(),
				e.getAcknowledgedBy(), e.getAcknowledgedAt(), e.getResolvedAt(),
				e.getExecutionLogId(), e.getDiagnosticLogId(), e.getCreatedAt(),
				null, null, null, null, List.of(), List.of(),
				List.of(), List.of(), List.of(), null);
	}
}
