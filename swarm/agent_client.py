import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import requests

APP_ROOT = Path(__file__).resolve().parent.parent
CALENDAR_PATH = APP_ROOT / "data" / "calendar.json"


def _load_busy_slots():
    try:
        if not CALENDAR_PATH.exists():
            return []
        with open(CALENDAR_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Normalize to datetime objects for comparison
            # Assuming format: "2026-02-08 09:00"
            busy = []
            for item in data.get("user_calendar", {}).get("busy_slots", []):
                start = datetime.fromisoformat(item["start"])
                end = datetime.fromisoformat(item["end"])
                busy.append((start, end))
            return busy
    except Exception:
        return []


def _is_busy(slot_dt, busy_slots, duration_minutes=60):
    # Simple check: if slot start matches any busy start or falls within
    # Ideally we'd check slot_dt + duration vs busy range
    # Hackathon simplified: just check if slot_dt is inside a busy range
    for start, end in busy_slots:
        if start <= slot_dt < end:
            return True
    return False


def _parse_slot(slot_str, date_hint=None):
    if not slot_str:
        return None
    if len(slot_str) == 5 and ":" in slot_str and date_hint:
        return datetime.fromisoformat(f"{date_hint} {slot_str}")
    try:
        return datetime.fromisoformat(slot_str)
    except ValueError:
        return None


def _pick_slot(availability, time_window, busy_slots=None):
    if not availability:
        return None
    date_hint = None
    if time_window:
        date_hint = time_window.get("date")
    parsed = [(slot, _parse_slot(slot, date_hint)) for slot in availability]
    parsed = [(slot, dt) for slot, dt in parsed if dt]
    if not parsed:
        return None
    
    # Filter out busy slots
    if busy_slots:
        parsed = [(slot, dt) for slot, dt in parsed if not _is_busy(dt, busy_slots)]
    
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

    service = payload.get("service", "appointment")
    window_desc = None
    if time_window:
        window_desc = (
            f"{time_window.get('date', '')} between "
            f"{time_window.get('start', '')} and {time_window.get('end', '')}"
        ).strip()
    service_clean = str(service).strip() or "appointment"
    article = "an" if service_clean[:1].lower() in {"a", "e", "i", "o", "u"} else "a"
    request_line = f"Agent: I'd like to book {article} {service_clean}"
    if window_desc:
        request_line = f"{request_line} for {window_desc}"
    request_line = f"{request_line}."

    # Load busy slots for conflict checking
    busy_slots = _load_busy_slots()
    
    slot = _pick_slot(availability, time_window, busy_slots)
    if not slot:
        return {
            "status": "no_availability",
            "provider": provider,
            "slot": None,
            "transcript": [
                f"{provider['name']}: Thank you for calling. How can we help?",
                request_line,
                f"{provider['name']}: Sorry, no slots match that request.",
                "Agent: Thanks for checking. Please let us know if anything opens up.",
            ],
        }
    return {
        "status": "ok",
        "provider": provider,
        "slot": slot,
        "transcript": [
            f"{provider['name']}: Thank you for calling. How can we help?",
            request_line,
            f"{provider['name']}: We can do {slot}.",
            "Agent: Great, please book it under Alex.",
            f"{provider['name']}: You're all set for {slot}.",
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
