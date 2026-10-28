"""JudobaseClient: retries, the limit on parallel requests, ids passed through.

The real judobase library is used with its methods replaced, so no request leaves
the machine.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from fake_judobase import country
from tenacity import wait_none

from ajr.sync.client import MAX_PARALLEL_REQUESTS, JudobaseClient


def without_pauses(method):
    """The same method with retries but without waiting between them."""
    return method.retry_with(wait=wait_none())


def test_network_errors_are_retried():
    async def scenario():
        async with JudobaseClient() as client:
            client.api.get_country_list = AsyncMock(
                side_effect=[ConnectionError("500"), TimeoutError(), [country(1)]]
            )
            countries = await without_pauses(JudobaseClient.countries)(client)
            return countries, client.api.get_country_list.await_count

    countries, attempts = asyncio.run(scenario())

    assert [c.id_country for c in countries] == [1]
    assert attempts == 3


def test_gives_up_after_four_attempts():
    async def scenario():
        async with JudobaseClient() as client:
            client.api.get_competition_list = AsyncMock(side_effect=ConnectionError("503"))
            with pytest.raises(ConnectionError, match="503"):
                await without_pauses(JudobaseClient.competitions)(client)
            return client.api.get_competition_list.await_count

    assert asyncio.run(scenario()) == 4


def test_other_errors_are_not_retried():
    async def scenario():
        async with JudobaseClient() as client:
            client.api.get_judoka_info = AsyncMock(side_effect=ValueError("bad data"))
            with pytest.raises(ValueError, match="bad data"):
                await without_pauses(JudobaseClient.judoka)(client, 7)
            return client.api.get_judoka_info.await_count

    assert asyncio.run(scenario()) == 1


def test_ids_are_passed_to_judobase():
    async def scenario():
        async with JudobaseClient() as client:
            client.api.find_contests = AsyncMock(return_value=[])
            client.api.get_judoka_info = AsyncMock(return_value=None)
            await client.contests(5)
            await client.judoka(7)
            return client.api

    api = asyncio.run(scenario())

    api.find_contests.assert_awaited_once_with(competition_id=5)
    api.get_judoka_info.assert_awaited_once_with(7)


def test_parallel_requests_are_limited():
    running = 0
    most_at_once = 0

    async def slow_request(competition_id):
        nonlocal running, most_at_once
        running += 1
        most_at_once = max(most_at_once, running)
        await asyncio.sleep(0.01)
        running -= 1
        return []

    async def scenario():
        async with JudobaseClient() as client:
            client.api.find_contests = slow_request
            await asyncio.gather(*(client.contests(i) for i in range(30)))

    asyncio.run(scenario())

    assert most_at_once == MAX_PARALLEL_REQUESTS
