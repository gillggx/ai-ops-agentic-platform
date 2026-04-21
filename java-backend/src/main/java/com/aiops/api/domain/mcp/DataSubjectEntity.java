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
@Table(name = "data_subjects",
		indexes = @Index(name = "ix_data_subjects_name", columnList = "name", unique = true))
public class DataSubjectEntity extends Auditable {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "name", nullable = false, length = 200, unique = true)
	private String name;

	@Column(name = "description", nullable = false, columnDefinition = "text")
	private String description = "";

	/** JSON text: {endpoint_url, method, headers} */
	@Column(name = "api_config", nullable = false, columnDefinition = "text")
	private String apiConfig = "{}";

	/** JSON text: fields array */
	@Column(name = "input_schema", nullable = false, columnDefinition = "text")
	private String inputSchema = "{}";

	/** JSON text: fields array */
	@Column(name = "output_schema", nullable = false, columnDefinition = "text")
	private String outputSchema = "{}";

	@Column(name = "is_builtin", nullable = false)
	private Boolean isBuiltin = Boolean.FALSE;
}
