SET NAMES utf8mb4;

ALTER TABLE settings
  ADD COLUMN IF NOT EXISTS podcast_dossier_json LONGTEXT NULL;

ALTER TABLE settings
  ADD COLUMN IF NOT EXISTS podcast_dossier_created_at TIMESTAMP NULL;
