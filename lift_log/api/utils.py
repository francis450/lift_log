"""Shared helpers for the whitelisted API. Nothing here is callable over HTTP."""

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate

from lift_log.permissions import NOT_SET_UP, ROLE
from lift_log.program import get_definition

DEFAULT_TZ = "Africa/Nairobi"
DEFAULT_REMINDERS = {"workout": True, "dinner": True, "checkin": True}


# --- Request guards and input parsing ---------------------------------------


def current_user() -> str:
	"""The signed-in user. Rejects Guest and users without the Lift Log User role."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Sign in to continue."), frappe.AuthenticationError)
	if ROLE not in frappe.get_roles(user):
		frappe.throw(_(NOT_SET_UP), frappe.PermissionError)
	return user


def parse_date(value, label: str = "date") -> date:
	try:
		return getdate(value)
	except Exception:
		frappe.throw(_("Invalid {0}: {1}").format(label, value))


def parse_utc(value) -> datetime | None:
	"""ISO 8601 (with Z or an offset) to a naive UTC datetime, which is how times are stored."""
	if value in (None, ""):
		return None
	try:
		dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
	except ValueError:
		frappe.throw(_("Invalid time: {0}").format(value))
	if dt.tzinfo:
		dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
	return dt


def iso_utc(value) -> str | None:
	if not value:
		return None
	dt = get_datetime(value)
	return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_utc() -> datetime:
	return datetime.now(timezone.utc).replace(tzinfo=None)


def as_list(value) -> list:
	if value in (None, ""):
		return []
	if isinstance(value, str):
		value = json.loads(value)
	if not isinstance(value, list):
		frappe.throw(_("Expected a list."))
	return value


def opt_number(value):
	"""Optional numbers are stored as 0 (Frappe numeric columns are NOT NULL) and returned as null."""
	return value or None


def conflict(stored: dict) -> dict:
	"""HTTP 409 for a stale write, with the stored record so the client can take it."""
	frappe.local.response.http_status_code = 409
	return {"stored": stored}


def is_stale(stored_at, incoming_at: datetime) -> bool:
	return bool(stored_at) and get_datetime(stored_at) > incoming_at


# --- Profile and program ----------------------------------------------------


def get_profile(user: str):
	if frappe.db.exists("LL Profile", user):
		return frappe.get_doc("LL Profile", user)
	return None


def default_program() -> str | None:
	programs = frappe.get_all("LL Program", order_by="start_date desc", pluck="name", limit=1)
	return programs[0] if programs else None


def program_of(profile) -> str | None:
	return (profile and profile.active_program) or default_program()


def program_and_definition(profile) -> tuple[str | None, dict | None]:
	program = program_of(profile)
	return program, get_definition(program)


def user_today(profile) -> date:
	tz = (profile and profile.time_zone) or DEFAULT_TZ
	return datetime.now(ZoneInfo(tz)).date()


def targets_of(profile) -> dict:
	return {
		"kcal": cint(profile and profile.kcal_target) or 2200,
		"protein_g": cint(profile and profile.protein_target_g) or None,
	}


def format_time(value) -> str | None:
	if value in (None, ""):
		return None
	if isinstance(value, timedelta):
		minutes = int(value.total_seconds()) // 60
		return f"{minutes // 60:02d}:{minutes % 60:02d}"
	return str(value)[:5]


# --- Serialisers ------------------------------------------------------------


def profile_dict(doc, with_program: bool = True) -> dict:
	reminders = doc.reminders
	if isinstance(reminders, str):
		reminders = json.loads(reminders or "null")
	out = {
		"user": doc.user,
		"weight_kg": opt_number(doc.weight_kg),
		"height_cm": opt_number(doc.height_cm),
		"age": opt_number(doc.age),
		"goal": doc.goal,
		"kcal_target": opt_number(doc.kcal_target),
		"kcal_target_manual": bool(doc.kcal_target_manual),
		"protein_target_g": opt_number(doc.protein_target_g),
		"protein_target_manual": bool(doc.protein_target_manual),
		"targets_note": doc.targets_note or None,
		"session_time": format_time(doc.session_time),
		"training_days": doc.training_days,
		"time_zone": doc.time_zone or DEFAULT_TZ,
		"active_program": doc.active_program,
		"ai_enabled": bool(doc.ai_enabled),
		"reminders": {**DEFAULT_REMINDERS, **(reminders or {})},
	}
	if with_program:
		out["program"] = get_definition(doc.active_program)
		out["exercises"] = exercise_library()
	return out


def exercise_library() -> dict:
	"""Every exercise's type, weight step and form link, keyed by name (the add-weight rule needs them)."""
	return {
		row.name: {"type": row.exercise_type, "increment_kg": row.increment_kg, "form_url": row.form_url}
		for row in frappe.get_all("LL Exercise", fields=["name", "exercise_type", "increment_kg", "form_url"])
	}


def parse_month(month: str):
	"""'2026-10' -> (first day, last day)."""
	import calendar

	try:
		year, mon = (int(part) for part in str(month).split("-"))
		first = date(year, mon, 1)
	except (ValueError, TypeError):
		frappe.throw(_("Invalid month: {0}. Use YYYY-MM.").format(month))
	return first, first.replace(day=calendar.monthrange(year, mon)[1])


def set_dict(row) -> dict:
	return {
		"exercise": row.exercise,
		"set_no": row.set_no,
		"kg": opt_number(row.kg),
		"amount": row.amount,
		"effort": row.effort or None,
		"done": bool(row.done),
	}


def session_dict(doc) -> dict:
	return {
		"name": doc.name,
		"session_date": str(doc.session_date),
		"program": doc.program,
		"week": doc.week or None,
		"routine_key": doc.routine_key,
		"routine_name": doc.routine_name,
		"status": doc.status,
		"started_at": iso_utc(doc.started_at),
		"finished_at": iso_utc(doc.finished_at),
		"note": doc.note or "",
		"client_updated_at": iso_utc(doc.client_updated_at),
		"sets": [set_dict(row) for row in doc.sets],
	}


def entry_dict(row) -> dict:
	return {
		"client_id": row.client_id,
		"meal": row.meal,
		"food_name": row.food_name,
		"portion": row.portion or "",
		"qty": row.qty,
		"kcal_per_portion": row.kcal_per_portion,
		"protein_per_portion": row.protein_per_portion,
		"source": row.source,
		"added_at": iso_utc(row.added_at),
	}


def food_day_dict(doc) -> dict:
	return {
		"food_date": str(doc.food_date),
		"client_updated_at": iso_utc(doc.client_updated_at),
		"entries": [entry_dict(row) for row in doc.entries],
	}


def day_totals(entries) -> dict:
	return {
		"kcal": round(sum(flt(e.qty) * flt(e.kcal_per_portion) for e in entries)),
		"protein_g": round(sum(flt(e.qty) * flt(e.protein_per_portion) for e in entries)),
		"entries": len(entries),
	}


def food_item_dict(item) -> dict:
	return {
		"name": item.get("name"),
		"food_name": item.get("food_name"),
		"portion": item.get("portion") or "",
		"kcal": item.get("kcal"),
		"protein_g": item.get("protein_g"),
	}


def checkin_dict(doc) -> dict:
	return {
		"name": doc.name,
		"week": doc.week,
		"checkin_date": str(doc.checkin_date),
		"program": doc.program,
		"weight_kg": opt_number(doc.weight_kg),
		"waist_cm": opt_number(doc.waist_cm),
		"forearm_cm": opt_number(doc.forearm_cm),
		"sleep": opt_number(doc.sleep),
		"energy": opt_number(doc.energy),
		"photo": doc.photo or None,
	}


def review_dict(doc) -> dict:
	stats = doc.stats
	if isinstance(stats, str):
		stats = json.loads(stats or "null")
	return {
		"name": doc.name,
		"program": doc.program,
		"week": doc.week,
		"period_start": str(doc.period_start) if doc.period_start else None,
		"period_end": str(doc.period_end) if doc.period_end else None,
		"stats": stats,
		"went_well": doc.went_well or "",
		"to_change": doc.to_change or "",
		"changes": [
			{
				"change_type": c.change_type,
				"title": c.title,
				"why": c.why or "",
				"exercise": c.exercise,
				"delta_kg": opt_number(c.delta_kg),
				"applies_from_week": c.applies_from_week,
				"accepted": bool(c.accepted),
			}
			for c in doc.changes
		],
		"model": doc.model,
		"generated_at": iso_utc(doc.generated_at),
	}


# --- Lookups ----------------------------------------------------------------


def session_name(user: str, day: date) -> str | None:
	return frappe.db.get_value("LL Workout Session", {"user": user, "session_date": day}, "name")


def food_day_name(user: str, day: date) -> str | None:
	return frappe.db.get_value("LL Food Day", {"user": user, "food_date": day}, "name")
