import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import aiomysql
from dotenv import load_dotenv

load_dotenv()

_DB_POOL = None


def _env(name: str, default=None):
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Environment variable {name} is required")
    return value


def _pool_loop(pool):
    return getattr(pool, "_loop", None)


def _pool_usable(pool) -> bool:
    if pool is None:
        return False
    loop = _pool_loop(pool)
    if loop is None:
        return True
    if getattr(loop, "is_closed", lambda: False)():
        return False
    try:
        current = asyncio.get_running_loop()
    except RuntimeError:
        return True
    return loop is current


async def _dispose_pool(pool) -> None:
    if pool is None:
        return
    try:
        pool.close()
        loop = _pool_loop(pool)
        if loop is not None and not loop.is_closed():
            await pool.wait_closed()
    except Exception:
        pass


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
    global _DB_POOL
    if _pool_usable(_DB_POOL):
        return _DB_POOL

    old_pool = _DB_POOL
    _DB_POOL = None
    await _dispose_pool(old_pool)

    _DB_POOL = await aiomysql.create_pool(**get_db_config())
    return _DB_POOL


async def close_db():
    global _DB_POOL
    pool = _DB_POOL
    _DB_POOL = None
    await _dispose_pool(pool)


@asynccontextmanager
async def get_conn_cursor(dict_cursor: bool = False):
    global _DB_POOL
    if not _pool_usable(_DB_POOL):
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
    text = Path(path).read_text(encoding="utf-8")
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        lines.append(line)
    text = "\n".join(lines)

    statements = []
    for part in text.split(";"):
        stmt = part.strip()
        if stmt:
            statements.append(stmt)

    async with get_conn_cursor() as (conn, cur):
        for stmt in statements:
            try:
                await cur.execute(stmt)
            except Exception as exc:
                print(f"[migration] ERROR executing: {stmt[:200]}... -> {exc}")
                raise
        await conn.commit()
