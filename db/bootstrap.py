import asyncio

from billing.pricing_seed import seed_pricing_defaults
from .connection import init_db
from .migrate import apply_migrations


async def bootstrap_db():
    await init_db()
    await apply_migrations()
    await seed_pricing_defaults()


def bootstrap_db_sync():
    # Invoke from sync code when there is no active event loop.
    asyncio.run(bootstrap_db())
