import asyncio
import os
from datetime import datetime

import requests


def _parse_slot(slot_str, date_hint=None):
    if not slot_str:
        return None
    if len(slot_str) == 5 and ":" in slot_str and date_hint:
        return datetime.fromisoformat(f"{date_hint} {slot_str}")
    try:
        return datetime.fromisoformat(slot_str)
    except ValueError:
        return None


def _pick_slot(availability, time_window):
    if not availability:
        return None
    date_hint = None
    if time_window:
        date_hint = time_window.get("date")
    parsed = [(slot, _parse_slot(slot, date_hint)) for slot in availability]
    parsed = [(slot, dt) for slot, dt in parsed if dt]
    if not parsed:
        return None
    if not time_window:
        return sorted(parsed, key=lambda item: item[1])[0][0]

    start = _parse_slot(time_window.get("start"), time_window.get("date"))
    end = _parse_slot(time_window.get("end"), time_window.get("date"))
    for slot, dt in sorted(parsed, key=lambda item: item[1]):
        if start and dt < start:
            continue
        if end and dt > end:
            continue
        return slot
    return None


async def _mock_call(provider, payload):
    await asyncio.sleep(provider.get("simulated_latency_s", 1.5))
    time_window = payload.get("time_window")
    availability = provider.get("availability", [])
    slot = _pick_slot(availability, time_window)
    if not slot:
        return {
            "status": "no_availability",
            "provider": provider,
            "slot": None,
            "transcript": [
                f"{provider['name']}: Sorry, no slots match that request."
            ],
        }
    return {
        "status": "ok",
        "provider": provider,
        "slot": slot,
        "transcript": [
            f"{provider['name']}: We can do {slot}.",
            "Agent: Great, please book it.",
        ],
    }


async def _http_call(provider, payload):
    endpoint = os.environ.get("AGENT_ENDPOINT")
    if not endpoint:
        return await _mock_call(provider, payload)

    def _post():
        response = requests.post(
            endpoint,
            json={"provider": provider, "request": payload},
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _post)


async def call_provider(provider, payload):
    mode = os.environ.get("AGENT_MODE", "mock").lower()
    if mode == "mock":
        return await _mock_call(provider, payload)
    return await _http_call(provider, payload)
