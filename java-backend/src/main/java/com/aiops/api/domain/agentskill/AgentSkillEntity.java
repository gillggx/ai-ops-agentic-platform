package com.aiops.api.domain.agentskill;

import jakarta.persistence.*;

import java.time.OffsetDateTime;

/**
 * 標準 Skill (V82, 2026-07-10) — a named instruction package the Coordinator
 * loads on demand: {@code whenToUse} rides in the agent's system-prompt index;
 * {@code body} is the full manual fetched via the load_skill tool. Distinct
 * from Domain Skills (skills_v2 = pipeline + automation).
 */
@Entity
@Table(name = "agent_skills")
public class AgentSkillEntity {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(nullable = false, unique = true, length = 64)
	private String name;

	@Column(name = "when_to_use", nullable = false, length = 300)
	private String whenToUse;

	@Column(nullable = false, columnDefinition = "text")
	private String body;

	@Column(nullable = false)
	private Boolean enabled = Boolean.TRUE;

	@Column(name = "updated_by", length = 64)
	private String updatedBy;

	@Column(name = "updated_at", nullable = false, columnDefinition = "timestamp with time zone")
	private OffsetDateTime updatedAt = OffsetDateTime.now();

	public Long getId() { return id; }
	public String getName() { return name; }
	public void setName(String name) { this.name = name; }
	public String getWhenToUse() { return whenToUse; }
	public void setWhenToUse(String whenToUse) { this.whenToUse = whenToUse; }
	public String getBody() { return body; }
	public void setBody(String body) { this.body = body; }
	public Boolean getEnabled() { return enabled; }
	public void setEnabled(Boolean enabled) { this.enabled = enabled; }
	public String getUpdatedBy() { return updatedBy; }
	public void setUpdatedBy(String updatedBy) { this.updatedBy = updatedBy; }
	public OffsetDateTime getUpdatedAt() { return updatedAt; }
	public void setUpdatedAt(OffsetDateTime updatedAt) { this.updatedAt = updatedAt; }
}
