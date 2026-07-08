package com.aiops.api.domain.chatdraft;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;

public interface ChatDraftRepository extends JpaRepository<ChatDraftEntity, Long> {

    /** Shelf view — newest first. */
    List<ChatDraftEntity> findByUserIdOrderByCreatedAtDesc(Long userId);

    /** Oldest-first UNMARKED drafts — used for ring-buffer eviction. */
    List<ChatDraftEntity> findByUserIdAndMarkedFalseOrderByCreatedAtAsc(Long userId);

    long countByUserId(Long userId);

    Optional<ChatDraftEntity> findByIdAndUserId(Long id, Long userId);

    @Modifying
    @Query("delete from ChatDraftEntity d where d.userId = :uid and d.marked = false")
    int deleteUnmarked(@Param("uid") Long userId);

    @Modifying
    @Query("delete from ChatDraftEntity d where d.userId = :uid")
    int deleteAllForUser(@Param("uid") Long userId);
}
