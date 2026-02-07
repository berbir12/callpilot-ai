import json
import os
from pathlib import Path

from flask import Flask, jsonify, request

from swarm.orchestrator import run_swarm_sync

APP_ROOT = Path(__file__).resolve().parent
PROVIDERS_PATH = APP_ROOT / "data" / "providers.json"

app = Flask(__name__)


def load_providers():
    with open(PROVIDERS_PATH, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data.get("providers", [])


def filter_providers(providers, service, limit):
    filtered = providers
    if service:
        filtered = [p for p in providers if p.get("service") == service]
    if limit:
        filtered = filtered[:limit]
    return filtered


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/swarm")
def swarm():
    payload = request.get_json(silent=True) or {}
    service = payload.get("service")
    limit = payload.get("limit")
    providers = filter_providers(load_providers(), service, limit)
    if not providers:
        return jsonify({"error": "no providers available"}), 400

    result = run_swarm_sync(payload, providers)
    return jsonify(result)


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
