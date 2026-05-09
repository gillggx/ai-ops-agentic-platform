package com.aiops.api.domain.skill;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface PersonalRuleFireRepository extends JpaRepository<PersonalRuleFireEntity, Long> {
    List<PersonalRuleFireEntity> findTop30ByPatrolIdOrderByFiredAtDesc(Long patrolId);
}
