"""judobase client with a limit on parallel requests and retries.

The judobase library raises ConnectionError on HTTP errors and aiohttp errors on
network failures. Both are retried a few times with a growing pause.
"""

import asyncio
import logging

from aiohttp import ClientError
from judobase import Competition, Contest, CountryShort, JudoBase, Judoka, RankingEntry
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

MAX_PARALLEL_REQUESTS = 8

REQUEST_TIMEOUT = 60  # seconds

retry_on_network_errors = retry(
    retry=retry_if_exception_type((ConnectionError, ClientError, TimeoutError)),
    stop=stop_after_attempt(4),
    wait=wait_exponential(min=2, max=16),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


class JudobaseClient:
    def __init__(self) -> None:
        # A big tournament's contests with their events are a few MB (Paris Grand Slam
        # 2024: 3.1 MB in 17 s); the library's default is 10 s.
        self.api = JudoBase(timeout=REQUEST_TIMEOUT)
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
    async def contests(self, competition_id: int, events: bool = False) -> list[Contest]:
        """With `events`: also the tags and the clock that tell a walkover from a fight
        (about 2.3 times the bytes)."""
        async with self.limit:
            return await self.api.find_contests(
                competition_id=competition_id, include="info,events" if events else "info"
            )

    @retry_on_network_errors
    async def judoka(self, judoka_id: int) -> Judoka:
        async with self.limit:
            return await self.api.get_judoka_info(judoka_id)

    @retry_on_network_errors
    async def world_ranking(self) -> list[RankingEntry]:
        """The current senior World Ranking List, every weight."""
        async with self.limit:
            return await self.api.world_ranking_list()
