"""Console entry point; intentionally does not install an autostart hook."""

from __future__ import annotations

import asyncio
import logging

from .agent import LifeOSWindowsAgent
from .config import AgentConfig


async def _run() -> None:
    agent = LifeOSWindowsAgent(AgentConfig.from_env())
    try:
        await agent.run()
    except KeyboardInterrupt:
        agent.stop()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
