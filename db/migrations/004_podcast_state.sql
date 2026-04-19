SET NAMES utf8mb4;

ALTER TABLE settings
  ADD COLUMN IF NOT EXISTS podcast_pending_json LONGTEXT NULL;

ALTER TABLE settings
  ADD COLUMN IF NOT EXISTS podcast_pending_created_at TIMESTAMP NULL;
