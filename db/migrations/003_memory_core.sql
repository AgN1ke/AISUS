-- db/migrations/003_memory_core.sql
-- 3-layer memory: CORE table, memory_long.is_core_memory, settings extensions
SET NAMES utf8mb4;

-- CORE memory: stable user facts (name, city, style, beliefs)
CREATE TABLE IF NOT EXISTS memory_core (
  id BIGINT NOT NULL AUTO_INCREMENT,
  chat_id BIGINT NOT NULL,
  fact_key VARCHAR(128) NOT NULL,
  fact_value TEXT NOT NULL,
  source ENUM('explicit','llm_extracted','inferred','heuristic','unknown') DEFAULT 'unknown',
  confidence FLOAT DEFAULT 100.0,
  tokens INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_core_chat_key (chat_id, fact_key),
  KEY idx_core_chat (chat_id),
  CONSTRAINT fk_core_chats FOREIGN KEY (chat_id)
    REFERENCES chats(chat_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Protect important long-term entries from cascade deletion
ALTER TABLE memory_long ADD COLUMN IF NOT EXISTS is_core_memory TINYINT(1) DEFAULT 0;

-- Memory persistence toggle per-chat
ALTER TABLE settings ADD COLUMN IF NOT EXISTS memory_persist_enabled TINYINT(1) DEFAULT 1;

-- Reflection tracking
ALTER TABLE settings ADD COLUMN IF NOT EXISTS last_reflection_at TIMESTAMP NULL;
