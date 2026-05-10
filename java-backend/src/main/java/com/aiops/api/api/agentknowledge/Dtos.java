package com.aiops.api.api.agentknowledge;

import com.aiops.api.domain.agentknowledge.*;

import java.time.OffsetDateTime;

/** DTOs for /api/v1/agent-{directives,knowledge,lexicon,examples}. */
public final class Dtos {
    private Dtos() {}

    public record DirectiveDto(
            Long id, String scopeType, String scopeValue,
            String title, String body, String priority,
            Boolean active, String source,
            OffsetDateTime createdAt, OffsetDateTime updatedAt,
            Long uses
    ) {
        public static DirectiveDto of(AgentDirectiveEntity e, long uses) {
            return new DirectiveDto(e.getId(), e.getScopeType(), e.getScopeValue(),
                    e.getTitle(), e.getBody(), e.getPriority(), e.getActive(), e.getSource(),
                    e.getCreatedAt(), e.getUpdatedAt(), uses);
        }
    }

    public record CreateDirectiveRequest(
            String scopeType, String scopeValue,
            String title, String body, String priority
    ) {}

    public record PatchDirectiveRequest(
            String scopeType, String scopeValue,
            String title, String body, String priority, Boolean active
    ) {}

    public record FireDto(Long id, OffsetDateTime firedAt, String sessionId, String context) {
        public static FireDto of(AgentDirectiveFireEntity e) {
            return new FireDto(e.getId(), e.getFiredAt(), e.getSessionId(), e.getContext());
        }
    }

    public record KnowledgeDto(
            Long id, String scopeType, String scopeValue,
            String title, String body, String priority,
            Boolean active, String source,
            Integer uses, OffsetDateTime lastUsedAt,
            OffsetDateTime createdAt, OffsetDateTime updatedAt
    ) {
        public static KnowledgeDto of(AgentKnowledgeEntity e) {
            return new KnowledgeDto(e.getId(), e.getScopeType(), e.getScopeValue(),
                    e.getTitle(), e.getBody(), e.getPriority(), e.getActive(), e.getSource(),
                    e.getUses(), e.getLastUsedAt(), e.getCreatedAt(), e.getUpdatedAt());
        }
    }

    public record CreateKnowledgeRequest(
            String scopeType, String scopeValue,
            String title, String body, String priority
    ) {}

    public record PatchKnowledgeRequest(
            String scopeType, String scopeValue,
            String title, String body, String priority, Boolean active
    ) {}

    public record LexiconDto(
            Long id, String term, String standard, String note,
            Integer uses, OffsetDateTime createdAt, OffsetDateTime updatedAt
    ) {
        public static LexiconDto of(AgentLexiconEntity e) {
            return new LexiconDto(e.getId(), e.getTerm(), e.getStandard(), e.getNote(),
                    e.getUses(), e.getCreatedAt(), e.getUpdatedAt());
        }
    }

    public record CreateLexiconRequest(String term, String standard, String note) {}
    public record PatchLexiconRequest(String term, String standard, String note) {}

    public record ExampleDto(
            Long id, String scopeType, String scopeValue,
            String title, String inputText, String outputText,
            Integer uses, OffsetDateTime lastUsedAt,
            OffsetDateTime createdAt, OffsetDateTime updatedAt
    ) {
        public static ExampleDto of(AgentExampleEntity e) {
            return new ExampleDto(e.getId(), e.getScopeType(), e.getScopeValue(),
                    e.getTitle(), e.getInputText(), e.getOutputText(),
                    e.getUses(), e.getLastUsedAt(), e.getCreatedAt(), e.getUpdatedAt());
        }
    }

    public record CreateExampleRequest(
            String scopeType, String scopeValue,
            String title, String inputText, String outputText
    ) {}

    public record PatchExampleRequest(
            String scopeType, String scopeValue,
            String title, String inputText, String outputText
    ) {}
}
