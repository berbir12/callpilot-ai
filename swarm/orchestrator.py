import asyncio

from swarm.agent_client import call_provider
from swarm.scoring import score_candidate


async def run_swarm(payload, providers, max_concurrency=5, timeout_s=25):
    semaphore = asyncio.Semaphore(max_concurrency)
    results = []

    async def run_one(provider):
        async with semaphore:
            try:
                return await asyncio.wait_for(
                    call_provider(provider, payload), timeout=timeout_s
                )
            except asyncio.TimeoutError:
                return {"status": "timeout", "provider": provider, "slot": None}
            except Exception as exc:  # noqa: BLE001 - capture for summary output
                return {
                    "status": "error",
                    "provider": provider,
                    "slot": None,
                    "error": str(exc),
                }

    tasks = [asyncio.create_task(run_one(provider)) for provider in providers]
    for task in asyncio.as_completed(tasks):
        results.append(await task)

    ranked = [
        score_candidate(result, payload)
        for result in results
        if result.get("status") == "ok"
    ]
    ranked.sort(key=lambda item: item["score"], reverse=True)
    best = ranked[0] if ranked else None

    return {
        "results": results,
        "ranked": ranked,
        "best": best,
    }


def run_swarm_sync(payload, providers, max_concurrency=5, timeout_s=25):
    return asyncio.run(run_swarm(payload, providers, max_concurrency, timeout_s))
