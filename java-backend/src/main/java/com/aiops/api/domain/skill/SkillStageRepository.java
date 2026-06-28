package com.aiops.api.domain.skill;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

/**
 * V65 (2026-06-28) — read/write surface for {@link SkillStageEntity}.
 *
 * <p>The Skill Studio service queries by skill_doc_id (load all three
 * stages at once) or by (skill_doc_id, kind) when only one stage is being
 * compiled or activated.
 */
@Repository
public interface SkillStageRepository extends JpaRepository<SkillStageEntity, Long> {

	List<SkillStageEntity> findBySkillDocId(Long skillDocId);

	Optional<SkillStageEntity> findBySkillDocIdAndKind(Long skillDocId, String kind);

	/** Phase 6+ scheduler dispatch query: every activated stage of a given
	 *  kind (e.g. "detect" — fan out to cron scheduler). */
	List<SkillStageEntity> findByKindAndStatus(String kind, String status);
}
