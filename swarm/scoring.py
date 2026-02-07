from datetime import datetime


def _parse_slot(slot_str, date_hint=None):
    if not slot_str:
        return None
    if len(slot_str) == 5 and ":" in slot_str and date_hint:
        return datetime.fromisoformat(f"{date_hint} {slot_str}")
    try:
        return datetime.fromisoformat(slot_str)
    except ValueError:
        return None


def _time_score(slot, time_window):
    if not slot:
        return 0.0
    if not time_window:
        return 0.6
    date_hint = time_window.get("date")
    start = _parse_slot(time_window.get("start"), date_hint)
    end = _parse_slot(time_window.get("end"), date_hint)
    slot_dt = _parse_slot(slot, date_hint)
    if not slot_dt:
        return 0.0
    if start and slot_dt < start:
        return 0.0
    if end and slot_dt > end:
        return 0.0
    if not start or not end:
        return 0.7
    total = (end - start).total_seconds()
    if total <= 0:
        return 0.7
    position = (slot_dt - start).total_seconds() / total
    return max(0.2, 1.0 - position)


def score_candidate(result, payload):
    provider = result.get("provider", {})
    preferences = payload.get("preferences", {})
    weights = {
        "time": preferences.get("time_weight", 0.6),
        "rating": preferences.get("rating_weight", 0.2),
        "distance": preferences.get("distance_weight", 0.2),
    }
    total_weight = sum(weights.values()) or 1.0
    weights = {key: value / total_weight for key, value in weights.items()}

    time_window = payload.get("time_window")
    time_component = _time_score(result.get("slot"), time_window)
    rating_component = min(provider.get("rating", 0) / 5.0, 1.0)
    distance = provider.get("distance_miles", 10)
    distance_component = max(0.1, 1.0 - min(distance / 10.0, 1.0))

    score = (
        weights["time"] * time_component
        + weights["rating"] * rating_component
        + weights["distance"] * distance_component
    )
    return {
        "provider": provider,
        "slot": result.get("slot"),
        "score": round(score, 3),
        "components": {
            "time": round(time_component, 3),
            "rating": round(rating_component, 3),
            "distance": round(distance_component, 3),
        },
    }
