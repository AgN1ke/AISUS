-- db/migrations/006_multitenant.sql
-- Multitenant: users, accounts, chat policies, turns, transactions,
-- provider keys pool, topups, pricing. Extends chats with owner_account_id.
-- See docs/project/multitenant-plan.md for full design.
SET NAMES utf8mb4;

-- Telegram users — one row per tg_user_id.
-- PK is user_id (native tg_user_id), consistent with existing `participants` table.
CREATE TABLE IF NOT EXISTS users (
  user_id BIGINT PRIMARY KEY,
  tg_username VARCHAR(64) NULL,
  first_name VARCHAR(128) NULL,
  last_name VARCHAR(128) NULL,
  lang_code VARCHAR(16) NULL,
  first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_users_username (tg_username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Billing identity. One user can own multiple accounts in theory, so surrogate PK.
CREATE TABLE IF NOT EXISTS accounts (
  account_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  owner_user_id BIGINT NOT NULL,
  balance_uah DECIMAL(12,4) NOT NULL DEFAULT 0,
  total_spent_uah DECIMAL(14,4) NOT NULL DEFAULT 0,
  total_topup_uah DECIMAL(14,4) NOT NULL DEFAULT 0,
  status ENUM('active','frozen','deleted') NOT NULL DEFAULT 'active',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_accounts_owner (owner_user_id),
  CONSTRAINT fk_accounts_users FOREIGN KEY (owner_user_id)
    REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Extend existing chats with billing linkage. chat_id stays as TG chat id.
ALTER TABLE chats ADD COLUMN IF NOT EXISTS owner_account_id BIGINT NULL;
ALTER TABLE chats ADD COLUMN IF NOT EXISTS tg_chat_type
  ENUM('private','group','supergroup','channel','unknown') DEFAULT 'unknown';
CREATE INDEX IF NOT EXISTS idx_chats_owner ON chats(owner_account_id);

-- Access policies per chat (configured by owner).
CREATE TABLE IF NOT EXISTS chat_policies (
  chat_id BIGINT PRIMARY KEY,
  access_mode ENUM('open','whitelist','admins_only','owner_only')
    NOT NULL DEFAULT 'open',
  per_user_daily_cap_uah DECIMAL(10,4) DEFAULT 5.0,
  per_chat_daily_cap_uah DECIMAL(10,4) DEFAULT 50.0,
  alert_threshold_pct TINYINT DEFAULT 80,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_chat_policies_chats FOREIGN KEY (chat_id)
    REFERENCES chats(chat_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Per-user access within a chat (whitelist / ban / delegated admin).
CREATE TABLE IF NOT EXISTS chat_access (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  chat_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  role ENUM('allowed','banned','delegated_admin') NOT NULL DEFAULT 'allowed',
  added_by BIGINT NULL,
  added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_chat_access (chat_id, user_id),
  KEY idx_chat_access_user (user_id),
  CONSTRAINT fk_chat_access_chats FOREIGN KEY (chat_id)
    REFERENCES chats(chat_id) ON DELETE CASCADE,
  CONSTRAINT fk_chat_access_users FOREIGN KEY (user_id)
    REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- User-level settings (personal defaults, override per chat via env/UI layer).
CREATE TABLE IF NOT EXISTS user_settings (
  user_id BIGINT NOT NULL,
  setting_key VARCHAR(64) NOT NULL,
  setting_value TEXT NULL,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, setting_key),
  CONSTRAINT fk_user_settings_users FOREIGN KEY (user_id)
    REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Turns — one logical user message, produces 1..N transactions.
-- turn_id is a UUID string (CHAR(36)) for cross-system debuggability.
CREATE TABLE IF NOT EXISTS turns (
  turn_id CHAR(36) PRIMARY KEY,
  account_id BIGINT NOT NULL,
  chat_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  tg_message_id BIGINT NULL,
  user_message_text TEXT NULL,
  route VARCHAR(32) NULL,
  capability VARCHAR(64) NULL,
  total_cost_uah DECIMAL(10,4) DEFAULT 0,
  status ENUM('running','completed','failed','budget_blocked','policy_blocked')
    NOT NULL DEFAULT 'running',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  completed_at TIMESTAMP NULL,
  KEY idx_turns_account_created (account_id, created_at),
  KEY idx_turns_chat_created (chat_id, created_at),
  KEY idx_turns_user_created (user_id, created_at),
  CONSTRAINT fk_turns_accounts FOREIGN KEY (account_id)
    REFERENCES accounts(account_id) ON DELETE CASCADE,
  CONSTRAINT fk_turns_chats FOREIGN KEY (chat_id)
    REFERENCES chats(chat_id) ON DELETE CASCADE,
  CONSTRAINT fk_turns_users FOREIGN KEY (user_id)
    REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Provider API keys pool (encrypted at rest).
-- encrypted_key stores AES-256-GCM ciphertext; master key lives in .env.
CREATE TABLE IF NOT EXISTS provider_keys (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  provider VARCHAR(32) NOT NULL,
  label VARCHAR(64) NULL,
  key_hash CHAR(64) NOT NULL,
  encrypted_key LONGTEXT NOT NULL,
  rpm_limit INT NULL,
  tpm_limit INT NULL,
  status ENUM('active','disabled','rate_limited','invalid') NOT NULL DEFAULT 'active',
  last_used_at TIMESTAMP NULL,
  last_error_at TIMESTAMP NULL,
  last_error TEXT NULL,
  cooldown_until TIMESTAMP NULL,
  total_requests BIGINT NOT NULL DEFAULT 0,
  total_spent_usd DECIMAL(14,6) NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_provider_keys_hash (provider, key_hash),
  KEY idx_provider_keys_status (provider, status, cooldown_until)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Transactions — one row per LLM/API call.
CREATE TABLE IF NOT EXISTS transactions (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  turn_id CHAR(36) NULL,
  account_id BIGINT NOT NULL,
  chat_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  kind ENUM('llm_call','search_api','tts','stt','fetch_page','other')
    NOT NULL DEFAULT 'llm_call',
  capability VARCHAR(64) NULL,
  provider VARCHAR(32) NULL,
  model VARCHAR(96) NULL,
  tokens_in INT NOT NULL DEFAULT 0,
  tokens_out INT NOT NULL DEFAULT 0,
  unit_count INT NOT NULL DEFAULT 0,
  cost_usd DECIMAL(12,6) NOT NULL DEFAULT 0,
  cost_uah DECIMAL(12,4) NOT NULL DEFAULT 0,
  markup_pct DECIMAL(6,2) NOT NULL DEFAULT 0,
  key_id BIGINT NULL,
  latency_ms INT NULL,
  status ENUM('success','failed','rate_limited') NOT NULL DEFAULT 'success',
  error_text TEXT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  KEY idx_tx_account_created (account_id, created_at),
  KEY idx_tx_turn (turn_id),
  KEY idx_tx_chat_created (chat_id, created_at),
  KEY idx_tx_user_created (user_id, created_at),
  CONSTRAINT fk_tx_turns FOREIGN KEY (turn_id)
    REFERENCES turns(turn_id) ON DELETE SET NULL,
  CONSTRAINT fk_tx_accounts FOREIGN KEY (account_id)
    REFERENCES accounts(account_id) ON DELETE CASCADE,
  CONSTRAINT fk_tx_chats FOREIGN KEY (chat_id)
    REFERENCES chats(chat_id) ON DELETE CASCADE,
  CONSTRAINT fk_tx_users FOREIGN KEY (user_id)
    REFERENCES users(user_id) ON DELETE CASCADE,
  CONSTRAINT fk_tx_keys FOREIGN KEY (key_id)
    REFERENCES provider_keys(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Topups — monobank invoices (used from Stage 5 onwards; earlier stages set balance manually).
CREATE TABLE IF NOT EXISTS topups (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  account_id BIGINT NOT NULL,
  amount_uah DECIMAL(10,2) NOT NULL,
  monopay_invoice_id VARCHAR(64) NULL,
  monopay_url TEXT NULL,
  status ENUM('created','pending','success','expired','failed','manual')
    NOT NULL DEFAULT 'created',
  note VARCHAR(255) NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  paid_at TIMESTAMP NULL,
  webhook_payload JSON NULL,
  UNIQUE KEY uq_topups_monopay (monopay_invoice_id),
  KEY idx_topups_account (account_id, created_at),
  CONSTRAINT fk_topups_accounts FOREIGN KEY (account_id)
    REFERENCES accounts(account_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Pricing — markup applied to provider base prices. UAH rate snapshot here for consistency.
CREATE TABLE IF NOT EXISTS pricing (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  provider VARCHAR(32) NOT NULL,
  model VARCHAR(96) NOT NULL,
  kind ENUM('llm','search','tts','stt','other') NOT NULL DEFAULT 'llm',
  input_usd_per_1m DECIMAL(10,4) NOT NULL DEFAULT 0,
  output_usd_per_1m DECIMAL(10,4) NOT NULL DEFAULT 0,
  unit_usd DECIMAL(10,6) NOT NULL DEFAULT 0,
  markup_pct DECIMAL(6,2) NOT NULL DEFAULT 40,
  uah_per_usd DECIMAL(8,4) NOT NULL DEFAULT 40,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_pricing_model (provider, model, kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
