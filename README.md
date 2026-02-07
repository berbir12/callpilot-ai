# callpilot-ai

Swarm orchestrator (Role 2) for running multiple appointment calls in parallel.

## Quick start

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## Example request

```bash
curl -X POST http://127.0.0.1:5000/swarm ^
  -H "Content-Type: application/json" ^
  -d "{\"service\":\"dentist\",\"limit\":3,\"time_window\":{\"date\":\"2026-02-08\",\"start\":\"13:00\",\"end\":\"17:00\"}}"
```

## Integration hooks

- Set `AGENT_MODE=mock` to use simulated providers (default).
- Set `AGENT_MODE=http` and `AGENT_ENDPOINT=http://host/agent` to forward each
  provider call to Role 1's agent service.