#!/usr/bin/env python3
"""Clear all bot memory (chat history) from database."""

import asyncio
import os
from dotenv import load_dotenv
import aiomysql

load_dotenv()

async def clear_memory():
    # Get DB config from env
    db_config = {
        "host": os.getenv("DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "aisus"),
        "password": os.getenv("DB_PASS", ""),
        "db": os.getenv("DB_NAME", "aisus"),
        "charset": "utf8mb4",
    }

    print(f"Connecting to {db_config['host']}:{db_config['port']}/{db_config['db']}...")

    try:
        conn = await aiomysql.connect(**db_config)
        async with conn.cursor() as cur:
            # Delete all recent memory (conversation history)
            await cur.execute("DELETE FROM memory_recent")
            recent_deleted = cur.rowcount

            # Delete all long-term memory (summaries)
            await cur.execute("DELETE FROM memory_long")
            long_deleted = cur.rowcount

            await conn.commit()

            print(f"✅ Memory cleared:")
            print(f"   - memory_recent: {recent_deleted} rows deleted")
            print(f"   - memory_long: {long_deleted} rows deleted")

        conn.close()
    except Exception as e:
        print(f"❌ Error: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(clear_memory())
