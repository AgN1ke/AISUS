# db/migrate.py
import os
from pathlib import Path
from .connection import execute, fetchone, run_sql_script_file

MIGRATIONS_DIR = Path(__file__).with_suffix("").parent / "migrations"

async def _ensure_migrations_table():
    await execute("""
    CREATE TABLE IF NOT EXISTS migrations_log (
      id INT AUTO_INCREMENT PRIMARY KEY,
      filename VARCHAR(255) NOT NULL,
      applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      UNIQUE KEY (filename)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """)

async def _is_applied(filename: str) -> bool:
    row = await fetchone("SELECT 1 FROM migrations_log WHERE filename=%s", (filename,))
    return bool(row)

async def _mark_applied(filename: str):
    await execute("INSERT INTO migrations_log (filename) VALUES (%s)", (filename,))

async def apply_migrations():
    await _ensure_migrations_table()
    # запускаємо всі .sql по порядку
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        fname = p.name
        if await _is_applied(fname):
            continue
        await run_sql_script_file(str(p))
        await _mark_applied(fname)
        print(f"[migration] applied {fname}")
