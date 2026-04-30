package com.aiops.api.api.alarm;

import java.time.OffsetDateTime;
import java.util.List;

/** DTOs for the redesigned Alarm Center (cluster-first view). */
public final class AlarmClusterDtos {

	private AlarmClusterDtos() {}

	/** One cluster row in the left rail. cluster_id == equipment_id (v1). */
	public record Cluster(String clusterId,
	                      String equipmentId,
	                      String bay,
	                      String severity,
	                      String title,
	                      String summary,
	                      List<String> triggerEvents,
	                      int count,
	                      int openCount,
	                      int ackCount,
	                      int resolvedCount,
	                      int affectedLots,
	                      OffsetDateTime firstAt,
	                      OffsetDateTime lastAt,
	                      List<Integer> spark,
	                      String cause,
	                      Double rootcauseConfidence,
	                      List<Long> alarmIds) {}

	public record ClusterListResponse(String since,
	                                  OffsetDateTime asOf,
	                                  int totalAlarms,
	                                  List<Cluster> clusters) {}

	public record Kpis(int activeAlarms,
	                   int openClusters,
	                   int highSeverityCount,
	                   Integer mttrMinutes,
	                   int autoCheckRunsLastHour,
	                   Double autoCheckAvgLatencyS,
	                   int healthScore) {}

	public record ClusterAckRequest(String equipmentId) {}

	public record ClusterAckResponse(String equipmentId, int acknowledged) {}
}
