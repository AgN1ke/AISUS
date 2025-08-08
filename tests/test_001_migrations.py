import pytest
from db.connection import fetchone, fetchall

@pytest.mark.asyncio
async def test_tables_exist():
    for t in ["chats","participants","glossary","threads","messages",
              "memory_recent","memory_long","settings","migrations_log","search_cache","page_cache"]:
        row = await fetchone(f"SHOW TABLES LIKE '{t}'")
        assert row is not None, f"table {t} missing"
