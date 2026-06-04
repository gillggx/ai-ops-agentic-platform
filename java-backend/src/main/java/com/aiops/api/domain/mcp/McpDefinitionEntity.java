package com.aiops.api.domain.mcp;

import com.aiops.api.domain.common.Auditable;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@Entity
@Table(name = "mcp_definitions",
		indexes = {
				@Index(name = "ix_mcp_definitions_name", columnList = "name", unique = true),
				@Index(name = "ix_mcp_definitions_system_mcp_id", columnList = "system_mcp_id"),
				@Index(name = "ix_mcp_definitions_data_subject_id", columnList = "data_subject_id")
		})
public class McpDefinitionEntity extends Auditable {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "name", nullable = false, length = 200, unique = true)
	private String name;

	@Column(name = "description", nullable = false, columnDefinition = "text")
	private String description = "";

	/** system | custom */
	@Column(name = "mcp_type", nullable = false, length = 10)
	private String mcpType = "custom";

	@Column(name = "api_config", columnDefinition = "text")
	private String apiConfig;

	@Column(name = "input_schema", columnDefinition = "text")
	private String inputSchema;

	/** Self-reference: custom MCP points at its system parent. */
	@Column(name = "system_mcp_id")
	private Long systemMcpId;

	/** Legacy link (being phased out). */
	@Column(name = "data_subject_id")
	private Long dataSubjectId;

	@Column(name = "processing_intent", nullable = false, columnDefinition = "text")
	private String processingIntent = "";

	@Column(name = "processing_script", columnDefinition = "text")
	private String processingScript;

	@Column(name = "output_schema", columnDefinition = "text")
	private String outputSchema;

	@Column(name = "ui_render_config", columnDefinition = "text")
	private String uiRenderConfig;

	@Column(name = "input_definition", columnDefinition = "text")
	private String inputDefinition;

	@Column(name = "sample_output", columnDefinition = "text")
	private String sampleOutput;

	@Column(name = "prefer_over_system", nullable = false)
	private Boolean preferOverSystem = Boolean.FALSE;

	/** private | public */
	@Column(name = "visibility", nullable = false, length = 10)
	private String visibility = "private";

	/** V54: 此 MCP 是否在 Pipeline Builder 有一個自動生成的 data block (source=mcp_auto)。 */
	@Column(name = "produces_block", nullable = false)
	private Boolean producesBlock = Boolean.FALSE;

	/** V54: 此 MCP 是否同時生成一個 1-block pipeline + published skill。 */
	@Column(name = "produces_skill", nullable = false)
	private Boolean producesSkill = Boolean.FALSE;

	/** V54: audit — JSON {llm_model, prompt_version, generated_at, last_regenerated_at} */
	@Column(name = "block_generation_meta", columnDefinition = "text")
	private String blockGenerationMeta;
}
