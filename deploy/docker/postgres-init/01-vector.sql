-- Ensure pgvector is available BEFORE Spring Boot runs ddl-auto.
-- Without this, tables that declare `vector(N)` columns (agent_examples,
-- agent_knowledge) fail to create on a brand-new database and the boot
-- silently leaves them missing. Mounted into the official postgres image
-- via /docker-entrypoint-initdb.d, so it runs exactly once on first init.
CREATE EXTENSION IF NOT EXISTS vector;
