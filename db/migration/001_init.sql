-- db/migrations/001_init.sql
-- Виконується в межах вже обраної БД (DB_NAME). Переконайся, що підключення йде до потрібної БД.
SET NAMES utf8mb4;
SET time_zone = '+00:00';

-- Основні таблиці

CREATE TABLE IF NOT EXISTS chats (
  chat_id BIGINT PRIMARY KEY,
  title VARCHAR(255) NULL,
  lang  VARCHAR(16) NULL,
  formality ENUM('casual','neutral','formal') DEFAULT 'neutral',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS participants (
  chat_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  username VARCHAR(64) NULL,
  display_name VARCHAR(255) NULL,
  role VARCHAR(32) NULL,
  last_active TIMESTAMP NULL,
  messages_count INT DEFAULT 0,
  PRIMARY KEY (chat_id, user_id),
  KEY idx_participants_user (user_id),
  CONSTRAINT fk_participants_chats FOREIGN KEY (chat_id)
    REFERENCES chats(chat_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS glossary (
  chat_id BIGINT NOT NULL,
  term VARCHAR(128) NOT NULL,
  definition TEXT NULL,
  usage_count INT DEFAULT 0,
  last_used TIMESTAMP NULL,
  status ENUM('new','confirmed','archived') DEFAULT 'new',
  PRIMARY KEY (chat_id, term),
  KEY idx_glossary_last_used (last_used),
  CONSTRAINT fk_glossary_chats FOREIGN KEY (chat_id)
    REFERENCES chats(chat_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS threads (
  chat_id BIGINT NOT NULL,
  thread_root_msg_id BIGINT NOT NULL,
  topic_summary TEXT NULL,
  started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  last_msg_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (chat_id, thread_root_msg_id),
  CONSTRAINT fk_threads_chats FOREIGN KEY (chat_id)
    REFERENCES chats(chat_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS messages (
  chat_id BIGINT NOT NULL,
  msg_id BIGINT NOT NULL,
  thread_root_msg_id BIGINT NULL,
  user_id BIGINT NULL,
  kind ENUM('text','photo','voice','video','doc','other') DEFAULT 'text',
  caption_text TEXT NULL,
  text LONGTEXT NULL,
  has_media TINYINT(1) DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (chat_id, msg_id),
  KEY idx_messages_thread (chat_id, thread_root_msg_id),
  CONSTRAINT fk_messages_chats FOREIGN KEY (chat_id)
    REFERENCES chats(chat_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS memory_recent (
  pos BIGINT NOT NULL AUTO_INCREMENT,
  chat_id BIGINT NOT NULL,
  role ENUM('system','user','assistant','tool') NOT NULL,
  content LONGTEXT NOT NULL,
  tokens INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (pos),
  KEY idx_recent_chat (chat_id, pos),
  CONSTRAINT fk_recent_chats FOREIGN KEY (chat_id)
    REFERENCES chats(chat_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS memory_long (
  id BIGINT NOT NULL AUTO_INCREMENT,
  chat_id BIGINT NOT NULL,
  summary LONGTEXT NOT NULL,
  importance FLOAT DEFAULT 0.5,
  usage_count INT DEFAULT 0,
  last_used TIMESTAMP NULL,
  tokens INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_long_chat (chat_id, importance, last_used),
  CONSTRAINT fk_long_chats FOREIGN KEY (chat_id)
    REFERENCES chats(chat_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS settings (
  chat_id BIGINT PRIMARY KEY,
  auth_ok TINYINT(1) DEFAULT 0,
  mode ENUM('bot','userbot') DEFAULT 'bot',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_settings_chats FOREIGN KEY (chat_id)
    REFERENCES chats(chat_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
