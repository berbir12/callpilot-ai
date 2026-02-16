import asyncio
import queue
import threading

from swarm.agent_client import call_provider
from swarm.scoring import score_candidate


async def run_swarm(payload, providers, max_concurrency=5, timeout_s=25):
    semaphore = asyncio.Semaphore(max_concurrency)
    results = []

    async def run_one(provider):
        async with semaphore:
            try:
                # Simulate "parallel" starts with small random jitter if mocking
                # This helps the visual dashboard look more organic
                await asyncio.sleep(0.1)
                return await asyncio.wait_for(
                    call_provider(provider, payload), timeout=timeout_s
                )
            except asyncio.TimeoutError:
                return {"status": "timeout", "provider": provider, "slot": None}
            except Exception as exc:  # noqa: BLE001
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


async def run_swarm_stream(payload, providers, max_concurrency=5, timeout_s=25):
    """
    Async generator that yields events as they happen.
    Events:
    - {"type": "start", "count": N}
    - {"type": "progress", "result": {...}}
    - {"type": "complete", "ranked": [...], "best": {...}}
    """
    semaphore = asyncio.Semaphore(max_concurrency)
    yield {"type": "start", "count": len(providers), "providers": providers}
    
    results = []
    
    async def run_one(provider):
        async with semaphore:
            try:
                # Small jitter for visual effect
                await asyncio.sleep(0.1)
                return await asyncio.wait_for(
                    call_provider(provider, payload), timeout=timeout_s
                )
            except asyncio.TimeoutError:
                return {"status": "timeout", "provider": provider, "slot": None}
            except Exception as exc:
                return {
                    "status": "error",
                    "provider": provider,
                    "slot": None,
                    "error": str(exc),
                }

    tasks = [asyncio.create_task(run_one(provider)) for provider in providers]
    
    # As tasks complete, yield their result immediately
    for task in asyncio.as_completed(tasks):
        result = await task
        results.append(result)
        # Score immediately so the UI can show a preliminary score? 
        # Or just show the raw result. Let's send the raw result + score if ok.
        scored_result = result
        if result.get("status") == "ok":
            scored = score_candidate(result, payload)
            scored_result = {
                **result,
                "score": scored["score"],
                "components": scored["components"],
            }

        yield {"type": "progress", "result": scored_result}

    # Final ranking
    ranked = [
        score_candidate(result, payload)
        for result in results
        if result.get("status") == "ok"
    ]
    ranked.sort(key=lambda item: item["score"], reverse=True)
    best = ranked[0] if ranked else None

    yield {
        "type": "complete",
        "ranked": ranked,
        "best": best,
    }

def run_swarm_sync(payload, providers, max_concurrency=5, timeout_s=25):
    return asyncio.run(run_swarm(payload, providers, max_concurrency, timeout_s))


def stream_swarm_sync(payload, providers, max_concurrency=5, timeout_s=25):
    updates = queue.Queue()

    async def producer():
        try:
            async for event in run_swarm_stream(
                payload, providers, max_concurrency, timeout_s
            ):
                updates.put(event)
        except Exception as e:
            updates.put({
                "type": "complete",
                "error": str(e),
                "ranked": [],
                "best": None,
            })
        finally:
            updates.put(None)

    def runner():
        try:
            asyncio.run(producer())
        except Exception as e:
            updates.put({
                "type": "complete",
                "error": str(e),
                "ranked": [],
                "best": None,
            })
            updates.put(None)

    threading.Thread(target=runner, daemon=True).start()

    while True:
        event = updates.get()
        if event is None:
            break
        yield event
