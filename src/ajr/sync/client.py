"""judobase client with a limit on parallel requests and retries.

The judobase library raises ConnectionError on HTTP errors and aiohttp errors on
network failures. Both are retried a few times with a growing pause.
"""

import asyncio
import logging

from aiohttp import ClientError
from judobase import Competition, Contest, CountryShort, JudoBase, Judoka
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

MAX_PARALLEL_REQUESTS = 8

retry_on_network_errors = retry(
    retry=retry_if_exception_type((ConnectionError, ClientError, TimeoutError)),
    stop=stop_after_attempt(4),
    wait=wait_exponential(min=2, max=16),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


class JudobaseClient:
    def __init__(self) -> None:
        self.api = JudoBase()
        self.limit = asyncio.Semaphore(MAX_PARALLEL_REQUESTS)

    async def __aenter__(self) -> JudobaseClient:
        await self.api.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.api.close_session()

    @retry_on_network_errors
    async def countries(self) -> list[CountryShort]:
        async with self.limit:
            return await self.api.get_country_list()

    @retry_on_network_errors
    async def competitions(self) -> list[Competition]:
        async with self.limit:
            return await self.api.get_competition_list()

    @retry_on_network_errors
    async def contests(self, competition_id: int) -> list[Contest]:
        async with self.limit:
            return await self.api.find_contests(competition_id=competition_id)

    @retry_on_network_errors
    async def judoka(self, judoka_id: int) -> Judoka:
        async with self.limit:
            return await self.api.get_judoka_info(judoka_id)
