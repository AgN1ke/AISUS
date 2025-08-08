# db/connection.py
import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
import aiomysql

load_dotenv()  # читає .env у корені проєкту

_DB_POOL = None

def _env(name: str, default=None):
    v = os.getenv(name, default)
    if v is None:
        raise RuntimeError(f"Environment variable {name} is required")
    return v

def get_db_config():
    return {
        "host": _env("DB_HOST", "127.0.0.1"),
        "port": int(_env("DB_PORT", "3306")),
        "user": _env("DB_USER", "aisus"),
        "password": _env("DB_PASS", ""),
        "db": _env("DB_NAME", "aisus"),
        "charset": "utf8mb4",
        "autocommit": True,
        "maxsize": int(_env("DB_POOL_SIZE", "10")),
    }

async def init_db():
    """Створює пул підключень до MariaDB (aiomysql). Викликається на старті бота."""
    global _DB_POOL
    if _DB_POOL:
        return _DB_POOL
    cfg = get_db_config()
    _DB_POOL = await aiomysql.create_pool(**cfg)
    return _DB_POOL

async def close_db():
    global _DB_POOL
    if _DB_POOL:
        _DB_POOL.close()
        await _DB_POOL.wait_closed()
        _DB_POOL = None

@asynccontextmanager
async def get_conn_cursor(dict_cursor: bool = False):
    """Універсальний контекст-менеджер: дає (conn, cursor)."""
    global _DB_POOL
    if _DB_POOL is None:
        await init_db()
    async with _DB_POOL.acquire() as conn:
        cursor_class = aiomysql.DictCursor if dict_cursor else aiomysql.Cursor
        async with conn.cursor(cursor_class) as cur:
            yield conn, cur

async def execute(sql: str, args=None):
    args = args or ()
    async with get_conn_cursor() as (_, cur):
        await cur.execute(sql, args)

async def fetchone(sql: str, args=None, dict_cursor: bool = True):
    args = args or ()
    async with get_conn_cursor(dict_cursor) as (_, cur):
        await cur.execute(sql, args)
        return await cur.fetchone()

async def fetchall(sql: str, args=None, dict_cursor: bool = True):
    args = args or ()
    async with get_conn_cursor(dict_cursor) as (_, cur):
        await cur.execute(sql, args)
        return await cur.fetchall()

async def run_sql_script_file(path: str):
    """Простий виконавець .sql-скриптів (без DELIMITER). Розбиває по ';'."""
    text = Path(path).read_text(encoding="utf-8")
    # Прибираємо коментарі '-- ...' та порожні рядки
    lines = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("--"):
            continue
        lines.append(ln)
    text = "\n".join(lines)

    # Наївний спліт по ';' (не підходить для процедур/тригерів — їх тут немає)
    statements = []
    buff = []
    for part in text.split(";"):
        buff.append(part)
        stmt = ";".join(buff).strip()
        if stmt:
            statements.append(stmt)
        buff = []

    async with get_conn_cursor() as (conn, cur):
        for stmt in statements:
            try:
                await cur.execute(stmt)
            except Exception as e:
                # для дебагу в лог
                print(f"[migration] ERROR executing: {stmt[:200]}... -> {e}")
                raise
        await conn.commit()
