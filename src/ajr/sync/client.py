"""judobase client with a limit on parallel requests and retries.

The judobase library raises ConnectionError on HTTP errors and aiohttp errors on
network failures. Both are retried a few times with a growing pause.
"""

import asyncio
import logging

from aiohttp import ClientError
from judobase import JudoBase

logger = logging.getLogger(__name__)

MAX_PARALLEL_REQUESTS = 8
MAX_ATTEMPTS = 4


class JudobaseClient:
    def __init__(self) -> None:
        self.api = JudoBase()
        self.limit = asyncio.Semaphore(MAX_PARALLEL_REQUESTS)

    async def __aenter__(self):
        await self.api.__aenter__()
        return self

    async def __aexit__(self, *exc):
        await self.api.close_session()

    async def request(self, description, make_request):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                async with self.limit:
                    return await make_request()
            except (ConnectionError, ClientError, TimeoutError) as error:
                if attempt == MAX_ATTEMPTS:
                    raise
                pause = 2**attempt
                logger.warning("%s failed (%r), retrying in %s s", description, error, pause)
                await asyncio.sleep(pause)

    async def countries(self):
        return await self.request("countries", lambda: self.api.get_country_list())

    async def competitions(self):
        return await self.request("competitions", lambda: self.api.get_competition_list())

    async def contests(self, competition_id: int):
        return await self.request(
            f"contests of competition {competition_id}",
            lambda: self.api.find_contests(competition_id=str(competition_id)),
        )

    async def judoka(self, judoka_id: int):
        return await self.request(
            f"judoka {judoka_id}",
            lambda: self.api.get_judoka_info(str(judoka_id)),
        )
