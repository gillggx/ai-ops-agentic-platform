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
@Table(name = "mock_data_sources",
		indexes = @Index(name = "ix_mock_data_sources_name", columnList = "name", unique = true))
public class MockDataSourceEntity extends Auditable {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "name", nullable = false, length = 200, unique = true)
	private String name;

	@Column(name = "description", nullable = false, columnDefinition = "text")
	private String description = "";

	@Column(name = "input_schema", columnDefinition = "text")
	private String inputSchema;

	/** Python code: `generate(params: dict) -> list | dict` */
	@Column(name = "python_code", columnDefinition = "text")
	private String pythonCode;

	@Column(name = "sample_output", columnDefinition = "text")
	private String sampleOutput;

	@Column(name = "is_active", nullable = false)
	private Boolean isActive = Boolean.TRUE;
}
