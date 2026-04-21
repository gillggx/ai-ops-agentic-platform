package com.aiops.api.domain.agent;

import com.aiops.api.domain.common.Auditable;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "agent_tools",
		indexes = {
				@Index(name = "ix_agent_tools_user_id", columnList = "user_id"),
				@Index(name = "ix_agent_tools_name", columnList = "name")
		})
public class AgentToolEntity extends Auditable {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "user_id", nullable = false)
	private Long userId;

	@Column(name = "name", nullable = false, length = 200)
	private String name;

	@Column(name = "code", nullable = false, columnDefinition = "text")
	private String code;

	@Column(name = "description", nullable = false, columnDefinition = "text")
	private String description = "";

	@Column(name = "usage_count", nullable = false)
	private Integer usageCount = 0;
}
