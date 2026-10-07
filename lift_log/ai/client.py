"""Shared Claude client (docs/05): settings, the per-user daily limit, logging, JSON parsing and validation.

Never logs prompt text or images: LL AI Log keeps model, token counts, latency and outcome only.
"""

import json
import math
import re
import time
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import frappe
from frappe import _

# Models that take output_config.format (structured outputs) and output_config.effort.
STRUCTURED_PREFIXES = ("claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5", "claude-opus-4-8", "claude-fable-5")
EFFORT_PREFIXES = ("claude-sonnet-5", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-fable-5")
# Server-side refusal fallback ("default" routing) is opted into on these.
FALLBACK_MODELS = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1")
FALLBACK_BETA = "server-side-fallback-2026-07-01"

NOT_SET_UP = "AI features aren't set up on your server"
LIMIT_REACHED = "Daily AI limit reached. It resets at midnight."
PARSE_FAILED = "Couldn't read the estimate. Try again."


class AIError(frappe.ValidationError):
	http_status_code = 502


class AITimeout(AIError):
	http_status_code = 504


class AINotSetUp(frappe.ValidationError):
	http_status_code = 503


class AIOff(frappe.ValidationError):
	http_status_code = 403


class AILimitReached(frappe.ValidationError):
	http_status_code = 429


def settings():
	return frappe.get_single("LL Settings")


def api_key(s=None) -> str | None:
	s = s or settings()
	return s.get_password("anthropic_api_key", raise_exception=False) or None


def ai_status(profile=None) -> dict:
	"""What the app needs to show or hide the AI tabs."""
	s = settings()
	if not s.ai_enabled or not api_key(s):
		return {"ready": False, "message": NOT_SET_UP}
	if profile is not None and not profile.ai_enabled:
		return {"ready": False, "message": "AI features are off. Turn them on in Settings."}
	return {"ready": True, "message": None}


def _today_start_system(user_tz: str) -> datetime:
	"""Midnight in the user's time zone, as a naive datetime in the site's time zone (LL AI Log.creation)."""
	tz = ZoneInfo(user_tz or "Africa/Nairobi")
	midnight = datetime.combine(datetime.now(tz).date(), dtime.min, tzinfo=tz)
	system = ZoneInfo(frappe.utils.get_system_timezone())
	return midnight.astimezone(system).replace(tzinfo=None)


def check_allowed(user: str, profile) -> None:
	"""Settings on, a key set, the user's AI switch on, and under the daily limit; else a clear error."""
	s = settings()
	if not s.ai_enabled or not api_key(s):
		frappe.throw(_(NOT_SET_UP), AINotSetUp)
	if profile is not None and not profile.ai_enabled:
		frappe.throw(_("AI features are off. Turn them on in Settings."), AIOff)
	limit = s.daily_ai_calls_per_user or 40
	used = frappe.db.count(
		"LL AI Log",
		{"user": user, "creation": [">=", _today_start_system(profile.time_zone if profile else None)]},
	)
	if used >= limit:
		frappe.throw(_(LIMIT_REACHED), AILimitReached)


def _supports(model: str, prefixes) -> bool:
	return any(model.startswith(p) for p in prefixes)


def _log(user, feature, model, started, ok, error_code=None, usage=None):
	frappe.get_doc(
		{
			"doctype": "LL AI Log",
			"user": user,
			"feature": feature,
			"model": model,
			"input_tokens": getattr(usage, "input_tokens", 0) or 0,
			"output_tokens": getattr(usage, "output_tokens", 0) or 0,
			"latency_ms": int((time.monotonic() - started) * 1000),
			"ok": 1 if ok else 0,
			"error_code": error_code,
		}
	).insert(ignore_permissions=True)
	# Keep the row even when the request then fails: it counts toward the daily limit and cost.
	frappe.db.commit()


def _create_message(*, key: str, timeout: float, params: dict, fallbacks: bool):
	"""The one place that talks to the Anthropic API (tests patch this)."""
	import anthropic

	client = anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=1)
	if fallbacks:
		return client.beta.messages.create(**params, betas=[FALLBACK_BETA], fallbacks="default")
	return client.messages.create(**params)


def complete(
	*,
	user: str,
	feature: str,
	model: str,
	content: list | str,
	timeout: float,
	schema: dict | None = None,
	effort: str | None = None,
	max_tokens: int = 8000,
	system: str | None = None,
) -> str:
	"""One Claude call. Returns the reply text; raises AIError subclasses with app-ready messages."""
	import anthropic

	params = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}]}
	if system:
		params["system"] = system
	output_config = {}
	if schema and _supports(model, STRUCTURED_PREFIXES):
		output_config["format"] = {"type": "json_schema", "schema": schema}
	if effort and _supports(model, EFFORT_PREFIXES):
		output_config["effort"] = effort
	if output_config:
		params["output_config"] = output_config

	started = time.monotonic()
	try:
		response = _create_message(
			key=api_key(), timeout=timeout, params=params, fallbacks=model in FALLBACK_MODELS
		)
	except anthropic.APITimeoutError:
		_log(user, feature, model, started, False, "timeout")
		frappe.throw(_("Claude took too long. Try again."), AITimeout)
	except anthropic.AuthenticationError:
		_log(user, feature, model, started, False, "auth")
		frappe.throw(_("The Anthropic API key on the server isn't valid."), AINotSetUp)
	except anthropic.RateLimitError:
		_log(user, feature, model, started, False, "rate_limited")
		frappe.throw(_("Claude is busy right now. Try again in a minute."), AIError)
	except anthropic.APIStatusError as e:
		_log(user, feature, model, started, False, f"http_{e.status_code}")
		frappe.throw(_("Claude couldn't answer right now. Try again."), AIError)
	except anthropic.APIConnectionError:
		_log(user, feature, model, started, False, "connection")
		frappe.throw(_("The server couldn't reach Claude. Try again."), AIError)

	usage = getattr(response, "usage", None)
	if response.stop_reason == "refusal":
		_log(user, feature, model, started, False, "refusal", usage)
		frappe.throw(_("Claude couldn't help with that one. Try describing it differently."), AIError)
	text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
	_log(user, feature, model, started, bool(text), None if text else f"empty_{response.stop_reason}", usage)
	return text


def parse_json(text: str):
	"""Whole reply, else the first fenced block, else the first [ or { to the last ] or }. None if none parse."""
	candidates = [text]
	fenced = re.search(r"```(?:json)?\s*(.*?)```", text or "", re.S)
	if fenced:
		candidates.append(fenced.group(1))
	starts = [i for i in ((text or "").find("["), (text or "").find("{")) if i >= 0]
	ends = [i for i in ((text or "").rfind("]"), (text or "").rfind("}")) if i >= 0]
	if starts and ends:
		candidates.append(text[min(starts) : max(ends) + 1])
	for candidate in candidates:
		try:
			return json.loads(candidate)
		except (TypeError, ValueError):
			continue
	return None


def complete_json(*, content: list | str, retry_suffix: str = "Reply with only the JSON.", **kwargs):
	"""complete() then parse; on a parse failure retry once with "Reply with only the JSON." appended."""
	data = parse_json(complete(content=content, **kwargs))
	if data is not None:
		return data
	if isinstance(content, str):
		retry = f"{content}\n\n{retry_suffix}"
	else:
		retry = [*content, {"type": "text", "text": retry_suffix}]
	data = parse_json(complete(content=retry, **kwargs))
	if data is None:
		frappe.throw(_(PARSE_FAILED), AIError)
	return data


def _number(value, upper: float) -> float | None:
	try:
		n = float(value)
	except (TypeError, ValueError):
		return None
	if not math.isfinite(n) or n < 0 or n >= upper:
		return None
	return n


def clean_items(raw) -> list[dict]:
	"""Keep food items with a name and sane numbers (finite, >= 0, kcal < 5000, protein < 300 g)."""
	if isinstance(raw, dict):
		raw = raw.get("items", [])
	items = []
	for item in raw if isinstance(raw, list) else []:
		if not isinstance(item, dict):
			continue
		name = str(item.get("food_name") or "").strip()
		kcal = _number(item.get("kcal"), 5000)
		protein = _number(item.get("protein_g"), 300)
		if not name or kcal is None or protein is None:
			continue
		items.append(
			{
				"food_name": name[:140],
				"portion": str(item.get("portion") or "").strip()[:140],
				"kcal": round(kcal),
				"protein_g": round(protein, 1),
			}
		)
	return items
