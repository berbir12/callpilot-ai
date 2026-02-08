import base64
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel

try:
	# Optional ElevenLabs SDK (latest). If missing, we fall back to mock.
	from elevenlabs.client import ElevenLabs
	from elevenlabs.conversational_ai.conversation import (
		Conversation,
		ConversationInitiationData,
	)
except Exception:  # pragma: no cover - optional dependency
	ElevenLabs = None
	Conversation = None
	ConversationInitiationData = None

try:
	import google.generativeai as genai
except Exception:  # pragma: no cover - optional dependency
	genai = None

APP_ROOT = Path(__file__).resolve().parent
CALENDAR_PATH = APP_ROOT / "data" / "calendar.json"

app = FastAPI(title="CallPilot Voice Agent", version="0.1.0")


class TimeWindow(BaseModel):
	date: Optional[str] = None
	start: Optional[str] = None
	end: Optional[str] = None


class AgentRequest(BaseModel):
	provider: Dict[str, Any]
	request: Dict[str, Any]


def _load_busy_slots() -> List[tuple[datetime, datetime]]:
	if not CALENDAR_PATH.exists():
		return []
	try:
		with open(CALENDAR_PATH, "r", encoding="utf-8") as handle:
			data = json.load(handle)
		busy = []
		for item in data.get("user_calendar", {}).get("busy_slots", []):
			start = datetime.fromisoformat(item["start"])
			end = datetime.fromisoformat(item["end"])
			busy.append((start, end))
		return busy
	except Exception:
		return []


def _is_busy(slot_dt: datetime, busy_slots: List[tuple[datetime, datetime]]) -> bool:
	for start, end in busy_slots:
		if start <= slot_dt < end:
			return True
	return False


def _parse_slot(slot_str: Optional[str], date_hint: Optional[str] = None) -> Optional[datetime]:
	if not slot_str:
		return None
	if len(slot_str) == 5 and ":" in slot_str and date_hint:
		return datetime.fromisoformat(f"{date_hint} {slot_str}")
	try:
		return datetime.fromisoformat(slot_str)
	except ValueError:
		return None


def _pick_slot(
	availability: List[str],
	time_window: Optional[Dict[str, Any]],
	busy_slots: List[tuple[datetime, datetime]],
) -> Optional[str]:
	if not availability:
		return None

	date_hint = None
	if time_window:
		date_hint = time_window.get("date")

	parsed = [(slot, _parse_slot(slot, date_hint)) for slot in availability]
	parsed = [(slot, dt) for slot, dt in parsed if dt]
	if not parsed:
		return None

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


def _get_elevenlabs_client() -> Optional["ElevenLabs"]:
	api_key = os.environ.get("ELEVENLABS_API_KEY")
	if not api_key or ElevenLabs is None:
		return None
	return ElevenLabs(api_key=api_key)


def _get_gemini_model():
	api_key = os.environ.get("GEMINI_API_KEY")
	if not api_key or genai is None:
		return None
	genai.configure(api_key=api_key)
	model_name = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
	return genai.GenerativeModel(model_name)


def _debug_enabled() -> bool:
	return os.environ.get("AGENT_DEBUG", "0") == "1"


def _fallback_receptionist_reply(availability: List[str]) -> str:
	if not availability:
		return "Sorry, we do not have any availability. [NO_AVAILABILITY]"
	options = ", ".join(availability[:3])
	return f"We have availability at {options}. Do any of these work for you?"


def _strip_markers(text: str) -> str:
	for marker in ("[BOOKED:", "[NO_AVAILABILITY]"):
		if marker in text:
			text = text.split(marker, 1)[0].strip()
	return text.strip()


def _extract_booked_slot(text: str) -> Optional[str]:
	if "[BOOKED:" not in text:
		return None
	start = text.find("[BOOKED:") + len("[BOOKED:")
	end = text.find("]", start)
	if end == -1:
		return None
	return text[start:end].strip()


def _call_elevenlabs_agent(message: str) -> Optional[str]:
	client = _get_elevenlabs_client()
	agent_id = os.environ.get("ELEVENLABS_AGENT_ID")
	if not client or not agent_id or Conversation is None or ConversationInitiationData is None:
		if _debug_enabled():
			print(
				"[agent] elevenlabs unavailable",
				{
					"client": bool(client),
					"agent_id": bool(agent_id),
					"sdk": bool(Conversation and ConversationInitiationData),
				},
				file=sys.stderr,
			)
		return None

	responses: List[str] = []
	ready = threading.Event()

	def _on_agent_response(response: str) -> None:
		responses.append(str(response))
		ready.set()

	config = ConversationInitiationData(
		conversation_config_override={"conversation": {"text_only": True}}
	)

	conversation = Conversation(
		client,
		agent_id,
		requires_auth=True,
		config=config,
		callback_agent_response=_on_agent_response,
	)

	try:
		if _debug_enabled():
			print("[agent] elevenlabs send", {"agent_id": agent_id}, file=sys.stderr)
		conversation.start_session()
		conversation.send_user_message(message)
	except Exception as exc:
		print("[agent] elevenlabs error", str(exc), file=sys.stderr)
		return None

	deadline = time.monotonic() + 10
	while time.monotonic() < deadline:
		if ready.wait(timeout=0.2):
			break

	if responses:
		if _debug_enabled():
			print("[agent] elevenlabs response", responses[-1], file=sys.stderr)
		return responses[-1]
	return None


def _call_gemini_receptionist(
	provider: Dict[str, Any],
	service: str,
	availability: List[str],
	busy_slots: List[tuple[datetime, datetime]],
	time_window: Optional[Dict[str, Any]],
	history: List[str],
) -> Optional[str]:
	model = _get_gemini_model()
	if not model:
		if _debug_enabled():
			print("[agent] gemini unavailable", file=sys.stderr)
		return None

	busy_desc = ", ".join(
		[f"{start.isoformat()} to {end.isoformat()}" for start, end in busy_slots]
	)
	availability_desc = ", ".join(availability) if availability else "none"
	window_desc = json.dumps(time_window or {}, ensure_ascii=True)
	conversation = "\n".join(history)

	prompt = (
		"You are a receptionist for the provider listed below. "
		"You must only offer times in the availability list and avoid busy slots. "
		"Respond with one short receptionist reply. "
		"If you confirm a booking, append [BOOKED: <slot>] with the slot you booked. "
		"If no slot is possible, append [NO_AVAILABILITY].\n\n"
		f"Provider: {provider.get('name')}\n"
		f"Service: {service}\n"
		f"Availability: {availability_desc}\n"
		f"Busy slots: {busy_desc or 'none'}\n"
		f"Requested window: {window_desc}\n\n"
		"Conversation so far:\n"
		f"{conversation}\n\n"
		"Receptionist reply:"
	)

	try:
		if _debug_enabled():
			print("[agent] gemini send", {"provider": provider.get("name")}, file=sys.stderr)
		response = model.generate_content(prompt, request_options={"timeout": 10})
		if _debug_enabled():
			print("[agent] gemini response", str(response.text).strip(), file=sys.stderr)
		return str(response.text).strip()
	except Exception as exc:
		print("[agent] gemini error", str(exc), file=sys.stderr)
		return None


def _collect_agent_lines(transcript: List[str]) -> List[str]:
	return [line for line in transcript if line.startswith("Agent:")]


def _tts_lines(lines: List[str]) -> Dict[int, str]:
	client = _get_elevenlabs_client()
	if not client:
		return {}

	voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
	audio_map: Dict[int, str] = {}
	for idx, line in enumerate(lines):
		# Generate short audio per agent line for demo purposes.
		audio = client.text_to_speech.convert(
			voice_id=voice_id,
			text=line,
			model_id="eleven_multilingual_v2",
		)
		audio_map[idx] = base64.b64encode(audio).decode("ascii")
	return audio_map


@app.get("/health")
def health() -> Dict[str, str]:
	return {"status": "ok"}


@app.post("/agent")
def run_agent(payload: AgentRequest) -> Dict[str, Any]:
	provider = payload.provider
	request_payload = payload.request
	print(
		"[agent] request",
		{"provider": provider.get("name"), "service": request_payload.get("service")},
		file=sys.stderr,
	)

	availability = provider.get("availability", [])
	time_window = request_payload.get("time_window")
	service = request_payload.get("service", "appointment")

	service_clean = str(service).strip() or "appointment"
	article = "an" if service_clean[:1].lower() in {"a", "e", "i", "o", "u"} else "a"

	window_desc = None
	if time_window:
		window_desc = (
			f"{time_window.get('date', '')} between "
			f"{time_window.get('start', '')} and {time_window.get('end', '')}"
		).strip()

	request_line = f"Agent: I'd like to book {article} {service_clean}"
	if window_desc:
		request_line = f"{request_line} for {window_desc}"
	request_line = f"{request_line}."

	busy_slots = _load_busy_slots()
	max_turns = int(os.environ.get("RECEPTIONIST_MAX_TURNS", "6"))
	max_seconds = int(os.environ.get("RECEPTIONIST_MAX_SECONDS", "25"))
	start_time = time.monotonic()

	transcript = [
		f"{provider.get('name', 'Provider')}: Thank you for calling. How can we help?",
		request_line,
	]
	history = [request_line]
	booked_slot = None

	for _ in range(max_turns):
		if time.monotonic() - start_time > max_seconds:
			print("[agent] receptionist timeout", {"provider": provider.get("name")}, file=sys.stderr)
			break

		receptionist_reply = _call_gemini_receptionist(
			provider,
			service_clean,
			availability,
			busy_slots,
			time_window,
			history,
		)
		if not receptionist_reply:
			receptionist_reply = _fallback_receptionist_reply(availability)

		booked_slot = _extract_booked_slot(receptionist_reply) or booked_slot
		transcript.append(
			f"{provider.get('name', 'Provider')}: {_strip_markers(receptionist_reply)}"
		)
		history.append(f"{provider.get('name', 'Provider')}: {_strip_markers(receptionist_reply)}")

		if "[NO_AVAILABILITY]" in receptionist_reply or booked_slot:
			break

		prompt = "\n".join(history) + "\nAgent:"
		agent_reply = _call_elevenlabs_agent(prompt)
		if agent_reply:
			agent_line = f"Agent: {agent_reply}"
		else:
			agent_line = "Agent: Could you share the earliest available slot?"
		transcript.append(agent_line)
		history.append(agent_line)

	slot = _pick_slot(availability, time_window, busy_slots)
	if booked_slot and booked_slot in availability:
		slot = booked_slot

	if not slot:
		transcript.append(
			f"{provider.get('name', 'Provider')}: Sorry, no slots match that request."
		)
		transcript.append("Agent: Thanks for checking. Please let us know if anything opens up.")
		return {
			"status": "no_availability",
			"provider": provider,
			"slot": None,
			"transcript": transcript,
			"tts_audio_b64": _tts_lines(_collect_agent_lines(transcript)),
		}


	transcript.append(f"{provider.get('name', 'Provider')}: We can do {slot}.")
	transcript.append("Agent: Great, please book it under Alex.")
	transcript.append(f"{provider.get('name', 'Provider')}: You're all set for {slot}.")
	print("[agent] completed", {"provider": provider.get("name"), "slot": slot}, file=sys.stderr)

	return {
		"status": "ok",
		"provider": provider,
		"slot": slot,
		"transcript": transcript,
		"tts_audio_b64": _tts_lines(_collect_agent_lines(transcript)),
	}