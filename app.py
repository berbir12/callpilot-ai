import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS

from swarm.orchestrator import run_swarm_sync, stream_swarm_sync
from places import search_nearby, search_all_services, save_providers

APP_ROOT = Path(__file__).resolve().parent
PROVIDERS_PATH = APP_ROOT / "data" / "providers.json"

app = Flask(__name__, static_folder='data')
CORS(app)  # Enable CORS for all routes


@app.errorhandler(500)
def handle_500(e):
    """Ensure 500 responses are JSON and log the real error."""
    import traceback
    traceback.print_exc()
    return jsonify({"error": "Internal server error", "detail": str(e)}), 500


def load_providers():
    try:
        with open(PROVIDERS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data.get("providers", [])
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[load_providers] {e}")
        return []


def filter_providers(providers, service, limit):
    filtered = providers
    if service:
        filtered = [p for p in providers if p.get("service") == service]
        # If no providers match the requested service, use all (demo fallback)
        if not filtered and providers:
            filtered = providers
    if limit:
        filtered = filtered[:limit]
    return filtered


def _load_busy_slots():
    calendar_path = APP_ROOT / "data" / "calendar.json"
    try:
        with open(calendar_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        busy = []
        for item in data.get("user_calendar", {}).get("busy_slots", []):
            start = datetime.fromisoformat(item["start"])
            end = datetime.fromisoformat(item["end"])
            busy.append((start, end))
        return busy
    except Exception:
        return []


def _overlaps(slot_start, slot_end, busy_slots):
    for busy_start, busy_end in busy_slots:
        if slot_start < busy_end and slot_end > busy_start:
            return True
    return False


def _parse_time(time_str, date_str):
    if not time_str or not date_str:
        return None
    return datetime.fromisoformat(f"{date_str} {time_str}")


def _filter_time_window(available, time_window):
    if not time_window:
        return available
    date_str = time_window.get("date")
    start = _parse_time(time_window.get("start"), date_str)
    end = _parse_time(time_window.get("end"), date_str)
    if not start and not end:
        return available
    filtered = []
    for slot in available:
        slot_dt = _parse_time(slot, date_str)
        if not slot_dt:
            continue
        if start and slot_dt < start:
            continue
        if end and slot_dt > end:
            continue
        filtered.append(slot)
    return filtered


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/")
def index():
    return jsonify(
        {
            "service": "CallPilot Swarm Orchestrator",
            "endpoints": ["/health", "/swarm", "/swarm/stream"],
        }
    )


@app.get("/data/calendar.json")
def get_calendar():
    """Serve calendar data for frontend. Never 500 - always return valid JSON."""
    try:
        calendar_path = APP_ROOT / "data" / "calendar.json"
        with open(calendar_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return jsonify(data)
    except Exception as e:
        print(f"[calendar] Error: {e}")
    return jsonify({"user_calendar": {"busy_slots": []}})


@app.post("/swarm")
def swarm():
    payload = request.get_json(silent=True) or {}
    service = payload.get("service")
    limit = payload.get("limit", 15)
    lat = payload.get("lat")
    lng = payload.get("lng")
    time_window = payload.get("time_window") or {}
    date = time_window.get("date")

    print(f"Payload: {payload}")

    # If lat/lng provided, fetch real providers from Google Places
    if lat is not None and lng is not None:
        try:
            radius = payload.get("radius", 5000)
            if service:
                providers = search_nearby(service, lat, lng, radius, limit, date=date)
            else:
                providers = search_all_services(lat, lng, radius, limit, date=date)
            save_providers(providers, merge=False)
        except Exception as e:
            print(f"[places] Error: {e}, falling back to providers.json")
            providers = filter_providers(load_providers(), service, limit)
    else:
        providers = filter_providers(load_providers(), service, limit)

    if not providers:
        return jsonify({"error": "no providers available"}), 400

    result = run_swarm_sync(payload, providers)
    return jsonify(result)


@app.post("/swarm/stream")
def swarm_stream():
    try:
        payload = request.get_json(silent=True) or {}
    except Exception as e:
        return jsonify({"error": f"Invalid JSON: {e}"}), 400

    service = payload.get("service")
    limit = payload.get("limit", 5)
    lat = payload.get("lat")
    lng = payload.get("lng")
    print("Payload received for streaming swarm:", payload)

    # Extract date from time_window for mock availability slots
    time_window = payload.get("time_window") or {}
    date = time_window.get("date")

    try:
        # If lat/lng provided, fetch real providers from Google Places
        if lat is not None and lng is not None:
            try:
                radius = payload.get("radius", 5000)
                if service:
                    providers = search_nearby(service, lat, lng, radius, limit, date=date)
                else:
                    providers = search_all_services(lat, lng, radius, limit, date=date)
                # Save to providers.json so the rest of the pipeline can reference them
                save_providers(providers, merge=False)
                print(f"[places] Found {len(providers)} providers via Google Places")
            except Exception as e:
                print(f"[places] Error: {e}, falling back to providers.json")
                providers = filter_providers(load_providers(), service, limit)
        else:
            providers = filter_providers(load_providers(), service, limit)
    except Exception as e:
        print(f"[swarm/stream] Error loading providers: {e}")
        return jsonify({"error": f"Failed to load providers: {e}"}), 500

    if not providers:
        return jsonify({"error": "no providers available"}), 400

    def event_stream():
        try:
            for event in stream_swarm_sync(payload, providers):
                yield json.dumps(event) + "\n"
        except Exception as e:
            print(f"[swarm/stream] Error: {e}")
            yield json.dumps({
                "type": "complete",
                "error": str(e),
                "ranked": [],
                "best": None,
            }) + "\n"

    return Response(stream_with_context(event_stream()), mimetype="application/x-ndjson")


@app.post("/providers/search")
def search_providers():
    """
    Search for nearby providers using Google Places API.

    Body JSON:
        service: str - one of 'dentist', 'auto_repair', 'doctor', 'hairdresser' (optional, searches all if omitted)
        lat: float - user latitude
        lng: float - user longitude
        radius: int - search radius in meters (default 5000)
        max_results: int - max providers per service (default 5)
        save: bool - whether to save results to providers.json (default true)
        merge: bool - whether to merge with existing providers (default false)
    """
    payload = request.get_json(silent=True) or {}
    lat = payload.get("lat")
    lng = payload.get("lng")

    if lat is None or lng is None:
        return jsonify({"error": "lat and lng are required"}), 400

    service = payload.get("service")
    radius = payload.get("radius", 5000)
    max_results = payload.get("max_results", 5)
    should_save = payload.get("save", True)
    merge = payload.get("merge", False)

    try:
        if service:
            providers = search_nearby(service, lat, lng, radius, max_results)
        else:
            providers = search_all_services(lat, lng, radius, max_results)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Places API error: {str(e)}"}), 500

    if should_save:
        save_providers(providers, merge=merge)

    return jsonify({
        "providers": providers,
        "count": len(providers),
        "saved": should_save,
    })


@app.post("/check-calendar")
def check_calendar():
    payload = request.get_json(silent=True) or {}
    date_str = payload.get("date")
    time_window = payload.get("time_window") or {}
    if not time_window:
        time_window = {
            "start": payload.get("start"),
            "end": payload.get("end"),
        }

    if not date_str:
        return jsonify({"error": "date is required"}), 400

    busy_slots = _load_busy_slots()

    window_start = _parse_time(time_window.get("start") or "09:00", date_str)
    window_end = _parse_time(time_window.get("end") or "17:00", date_str)
    if not window_start or not window_end or window_start >= window_end:
        return jsonify({"error": "invalid time window"}), 400

    available = []
    slot_start = window_start
    while slot_start < window_end:
        slot_end = slot_start + timedelta(minutes=60)
        if slot_end > window_end:
            break
        if not _overlaps(slot_start, slot_end, busy_slots):
            available.append(
                {
                    "date": date_str,
                    "start": slot_start.strftime("%H:%M"),
                    "end": slot_end.strftime("%H:%M"),
                }
            )
        slot_start = slot_start + timedelta(minutes=60)

    return jsonify({"available_slots": available})


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
