"""Daily log: morning weight, sleep, steps and pain (docs: baseline data). One record per user per day."""

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, flt

from lift_log import trend
from lift_log.api.utils import (
	conflict,
	current_user,
	daily_log_dict,
	daily_log_name,
	get_profile,
	is_stale,
	now_utc,
	parse_date,
	parse_utc,
	user_today,
)

MAX_DAYS = 120


@frappe.whitelist(methods=["GET"])
def get(date: str | None = None) -> dict:
	"""The day's log (or an empty one) and the weight trend up to that day."""
	user = current_user()
	day = parse_date(date) if date else user_today(get_profile(user))
	name = daily_log_name(user, day)
	return {
		"log": daily_log_dict(frappe.get_doc("LL Daily Log", name)) if name else None,
		"trend": trend.summary(_weights(user, day - timedelta(days=13), day), day),
	}


@frappe.whitelist(methods=["POST"])
def save(
	log_date: str,
	client_updated_at: str | None = None,
	weight_kg=None,
	sleep_hours=None,
	steps=None,
	pain=None,
	pain_area=None,
	note=None,
) -> dict:
	"""Upsert by (user, log_date). A field left out keeps its stored value; an empty string clears it,
	so weight in the morning and steps at night can be saved separately.
	A write older than the stored one gets HTTP 409 and the stored log."""
	user = current_user()
	day = parse_date(log_date, "log_date")
	incoming_at = parse_utc(client_updated_at) or now_utc()

	name = frappe.db.get_value("LL Daily Log", {"user": user, "log_date": day}, "name", for_update=True)
	if name:
		doc = frappe.get_doc("LL Daily Log", name)
		if is_stale(doc.client_updated_at, incoming_at):
			return conflict(daily_log_dict(doc))
	else:
		doc = frappe.new_doc("LL Daily Log")
		doc.user = user
		doc.log_date = day

	numbers = {"weight_kg": (weight_kg, flt), "sleep_hours": (sleep_hours, flt), "steps": (steps, cint)}
	for field, (value, cast) in numbers.items():
		if value is None:
			continue
		if value != "" and cast(value) < 0:
			frappe.throw(_("{0} can't be negative.").format(field))
		doc.set(field, 0 if value == "" else cast(value))
	if pain is not None:
		doc.pain = "" if pain == "" else str(cint(pain))
	if pain_area is not None:
		doc.pain_area = (pain_area or "").strip()[:140]
	if note is not None:
		doc.note = (note or "").strip()[:1000]
	doc.client_updated_at = incoming_at
	doc.save()
	return daily_log_dict(doc)


@frappe.whitelist(methods=["GET"])
def recent(days: int = 28, until: str | None = None) -> dict:
	"""The last N days (max 120), oldest first, each with its 7-day average, plus the current trend."""
	user = current_user()
	end = parse_date(until) if until else user_today(get_profile(user))
	days = min(max(cint(days) or 28, 1), MAX_DAYS)
	start = end - timedelta(days=days - 1)
	logs = {
		str(d.log_date): daily_log_dict(d)
		for d in (
			frappe.get_doc("LL Daily Log", n)
			for n in frappe.get_all(
				"LL Daily Log",
				filters={"user": user, "log_date": ["between", [start, end]]},
				order_by="log_date asc",
				pluck="name",
			)
		)
	}
	weights = _weights(user, start - timedelta(days=trend.WINDOW_DAYS - 1), end)
	points = trend.rolling(weights, start, end)
	return {
		"days": [{**p, "log": logs.get(p["date"])} for p in points],
		"trend": trend.summary(weights, end),
	}


def _weights(user: str, start, end) -> dict:
	rows = frappe.get_all(
		"LL Daily Log",
		filters={"user": user, "log_date": ["between", [start, end]], "weight_kg": [">", 0]},
		fields=["log_date", "weight_kg"],
	)
	return {r.log_date: flt(r.weight_kg) for r in rows}
