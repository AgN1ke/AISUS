-- db/migrations/002_search_cache.sql
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS search_cache (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  provider VARCHAR(32) NOT NULL,
  query_hash CHAR(64) NOT NULL,
  query_text TEXT NOT NULL,
  results_json LONGTEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  KEY idx_search_qh (provider, query_hash),
  KEY idx_search_ts (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS page_cache (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  url_hash CHAR(64) NOT NULL,
  url TEXT NOT NULL,
  text LONGTEXT NOT NULL,
  fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  KEY idx_page_uh (url_hash),
  KEY idx_page_ts (fetched_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
