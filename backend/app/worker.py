from __future__ import annotations

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("id8.worker")


async def main() -> None:
    logger.info("ID8 worker started — waiting for orchestrator implementation")
    # TODO: poll for pending runs and retry jobs, execute orchestrator
    while True:
        await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
