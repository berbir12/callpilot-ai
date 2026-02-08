# CallPilot AI

Agentic Voice AI for autonomous appointment scheduling. This repo contains:

- `app.py`: Flask swarm orchestrator that fans out parallel calls, scores results, and streams updates.
- `agent.py`: FastAPI voice agent that uses ElevenLabs + an LLM receptionist to negotiate slots.
- `frontend/`: React dashboard (see `frontend/README.md`).

## Quick start (orchestrator)

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

The orchestrator runs on `http://127.0.0.1:5000`.

## Quick start (voice agent)

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn agent:app --reload --port 8000
```

The voice agent runs on `http://127.0.0.1:8000`.

## Environment variables

Orchestrator (`app.py`)

- `AGENT_MODE`: `mock` (default) or `http`
- `AGENT_ENDPOINT`: URL to the voice agent when `AGENT_MODE=http` (e.g. `http://127.0.0.1:8000/agent`)
- `GOOGLE_PLACES_API_KEY`: required to fetch real providers with lat/lng
- `HOST`, `PORT`, `FLASK_DEBUG`: Flask server settings

Voice agent (`agent.py`)

- `ELEVENLABS_API_KEY`: ElevenLabs API key
- `ELEVENLABS_AGENT_ID`: ElevenLabs Conversational AI agent ID
- `AZURE_OPENAI_API_KEY`: Azure OpenAI API key
- `AZURE_OPENAI_ENDPOINT`: Azure OpenAI endpoint URL
- `AZURE_OPENAI_MODEL`: model name (default `gpt-4o`)
- `RECEPTIONIST_MAX_TURNS`: max conversation turns (default `6`)
- `RECEPTIONIST_MAX_SECONDS`: max seconds per call (default `25`)

## API overview

- `GET /health`: health check
- `POST /swarm`: run a swarm of provider calls (JSON response)
- `POST /swarm/stream`: NDJSON stream of swarm progress events
- `POST /providers/search`: fetch providers via Google Places
- `POST /check-calendar`: check availability vs `data/calendar.json`
- `GET /data/calendar.json`: returns calendar data for the UI

### Swarm request (JSON)

```bash
curl -X POST http://127.0.0.1:5000/swarm ^
  -H "Content-Type: application/json" ^
  -d "{\"service\":\"dentist\",\"limit\":3,\"time_window\":{\"date\":\"2026-02-08\",\"start\":\"13:00\",\"end\":\"17:00\"},\"preferences\":{\"time_weight\":0.6,\"rating_weight\":0.2,\"distance_weight\":0.2}}"
```

### Streaming updates (NDJSON)

```bash
curl.exe -N -X POST http://127.0.0.1:5000/swarm/stream ^
  -H "Content-Type: application/json" ^
  -d "{\"service\":\"dentist\",\"limit\":3,\"time_window\":{\"date\":\"2026-02-08\",\"start\":\"13:00\",\"end\":\"17:00\"}}"
```

### Provider search (Google Places)

```bash
curl -X POST http://127.0.0.1:5000/providers/search ^
  -H "Content-Type: application/json" ^
  -d "{\"service\":\"doctor\",\"lat\":31.206,\"lng\":74.269,\"radius\":5000,\"max_results\":5,\"save\":true,\"merge\":false}"
```

### Calendar availability check

```bash
curl -X POST http://127.0.0.1:5000/check-calendar ^
  -H "Content-Type: application/json" ^
  -d "{\"date\":\"2026-02-08\",\"start\":\"09:00\",\"end\":\"17:00\"}"
```

## Data files

- `data/providers.json`: mock provider directory (used when `AGENT_MODE=mock` or no lat/lng).
- `data/calendar.json`: busy slots and user preferences for conflict checks.

## Notes

- Add `lat`/`lng` to `/swarm` requests to auto-fetch providers from Google Places.
- The swarm scorer ranks candidates by time window fit, rating, and distance.