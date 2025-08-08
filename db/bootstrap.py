import asyncio
from .connection import init_db
from .migrate import apply_migrations

async def bootstrap_db():
    await init_db()
    await apply_migrations()

def bootstrap_db_sync():
    # Викликати з синхронного коду без активного event loop
    asyncio.run(bootstrap_db())
