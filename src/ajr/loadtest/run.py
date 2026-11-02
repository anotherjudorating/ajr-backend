"""Calling the API: one call, a pass over every case, and the load of many clients."""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from ajr.loadtest.cases import Case

# PostgREST's EXPLAIN of the call (db-plan-enabled): how many pages it read.
PLAN = "application/vnd.pgrst.plan+json; options=analyze|buffers"
CLIENT_TIMEOUT = 60  # seconds: the database gives up long before (statement timeout)


@dataclass
class Result:
    status: int  # 0: no answer
    ms: float
    error: str = ""
    pages: int | None = None  # shared buffers hit and read (with --plan)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300  # 204: a function that returns nothing


class Api:
    """The Data API's functions, called as the site calls them (POST /rpc/<name>)."""

    def __init__(self, base: str, key: str = "") -> None:
        self.base = base.rstrip("/")
        self.headers = {"apikey": key} if key else {}
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> Api:
        self.session = aiohttp.ClientSession(
            headers=self.headers, timeout=aiohttp.ClientTimeout(total=CLIENT_TIMEOUT)
        )
        return self

    async def __aexit__(self, *exc) -> None:
        await self.session.close()

    async def json(self, function: str, params: dict | None = None):
        """The answer of a call, for picking the cases; it must work."""
        async with self.session.post(f"{self.base}/rpc/{function}", json=params or {}) as response:
            response.raise_for_status()
            return await response.json()

    async def call(self, case: Case, plan: bool = False) -> Result:
        headers = {"Accept": PLAN} if plan else {}
        start = time.perf_counter()
        try:
            async with self.session.post(
                f"{self.base}/rpc/{case.function}", json=case.params, headers=headers
            ) as response:
                body = await response.read()
                ms = (time.perf_counter() - start) * 1000
                if not 200 <= response.status < 300:
                    return Result(response.status, ms, body.decode(errors="replace")[:300])
                if plan and response.status == 200:
                    top = (await response.json())[0]["Plan"]
                    return Result(
                        200, ms, pages=top["Shared Hit Blocks"] + top["Shared Read Blocks"]
                    )
                return Result(response.status, ms)
        except (aiohttp.ClientError, TimeoutError) as error:
            return Result(0, (time.perf_counter() - start) * 1000, repr(error))


async def one_by_one(api: Api, cases: list[Case], plan: bool = False) -> list[Result]:
    """Every case once, one after the other: the first pass meets the cache cold."""
    return [await api.call(case, plan) for case in cases]


@dataclass
class Load:
    clients: int
    calls: int
    seconds: float
    p50: float
    p95: float
    p99: float
    failures: list[dict]


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))] if ordered else 0.0


async def under_load(api: Api, cases: list[Case], clients: int, rng: random.Random) -> Load:
    """Every case once, in a random order, by `clients` calling at the same time."""
    queue: asyncio.Queue[Case] = asyncio.Queue()
    for case in rng.sample(cases, len(cases)):
        queue.put_nowait(case)
    results: list[tuple[Case, Result]] = []

    async def client() -> None:
        while not queue.empty():
            case = queue.get_nowait()
            results.append((case, await api.call(case)))

    start = time.perf_counter()
    await asyncio.gather(*(client() for _ in range(clients)))
    times = [r.ms for _, r in results]
    return Load(
        clients=clients,
        calls=len(results),
        seconds=round(time.perf_counter() - start, 1),
        p50=round(percentile(times, 0.50)),
        p95=round(percentile(times, 0.95)),
        p99=round(percentile(times, 0.99)),
        failures=[{"case": c.key, **asdict(r)} for c, r in results if not r.ok],
    )
