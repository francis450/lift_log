import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from lift_log.api.utils import (
	checkin_dict,
	current_user,
	get_profile,
	opt_number,
	parse_date,
	program_and_definition,
	user_today,
)
from lift_log.program import week_count, week_dates, week_for

MEASUREMENT_DUE_DAYS = 14


def _resolve_week(definition: dict | None, week, fallback_day) -> int:
	week = cint(week) or (week_for(definition, fallback_day) if definition else None)
	if not week or (definition and not 1 <= week <= week_count(definition)):
		frappe.throw(_("Invalid program week: {0}").format(week))
	return week


@frappe.whitelist(methods=["GET"])
def get(week: int | None = None) -> dict:
	"""The week's check-in (or null) plus what the check-in screen prefills and flags:
	last week's weight, and whether waist and forearm are due (last measured 14+ days ago or never)."""
	user = current_user()
	profile = get_profile(user)
	program, definition = program_and_definition(profile)
	week = _resolve_week(definition, week, user_today(profile))

	name = frappe.db.get_value("LL Check In", {"user": user, "program": program, "week": week}, "name")
	checkin = frappe.get_doc("LL Check In", name) if name else None
	reference_day = checkin.checkin_date if checkin else (week_dates(definition, week)[-1] if definition else user_today(profile))

	earlier = frappe.get_all(
		"LL Check In",
		filters={"user": user, "program": program, "week": ["<", week]},
		fields=["checkin_date", "weight_kg", "waist_cm", "forearm_cm"],
		order_by="week desc",
	)
	previous_weight = next((c.weight_kg for c in earlier if c.weight_kg), None) or (profile and profile.weight_kg)

	def last_measured(field):
		day = next((c.checkin_date for c in earlier if c.get(field)), None)
		return str(day) if day else None

	last = {"waist": last_measured("waist_cm"), "forearm": last_measured("forearm_cm")}
	return {
		"week": week,
		"checkin": checkin_dict(checkin) if checkin else None,
		"previous_weight_kg": opt_number(previous_weight),
		"last_measured": last,
		"due": {
			key: not day or (getdate(reference_day) - getdate(day)).days >= MEASUREMENT_DUE_DAYS
			for key, day in last.items()
		},
	}


@frappe.whitelist(methods=["POST"])
def save(
	week: int | None = None,
	checkin_date: str | None = None,
	weight_kg=None,
	waist_cm=None,
	forearm_cm=None,
	sleep=None,
	energy=None,
) -> dict:
	"""Upsert the check-in for (user, program, week). The latest check-in updates the profile weight."""
	user = current_user()
	profile = get_profile(user)
	program, definition = program_and_definition(profile)
	day = parse_date(checkin_date, "checkin_date") if checkin_date else user_today(profile)
	week = _resolve_week(definition, week, day)
	if flt(weight_kg) <= 0:
		frappe.throw(_("Enter your body weight."))

	name = frappe.db.get_value("LL Check In", {"user": user, "program": program, "week": week}, "name", for_update=True)
	doc = frappe.get_doc("LL Check In", name) if name else frappe.new_doc("LL Check In")
	doc.update(
		{
			"user": user,
			"program": program,
			"week": week,
			"checkin_date": day,
			"weight_kg": flt(weight_kg),
			"waist_cm": flt(waist_cm),
			"forearm_cm": flt(forearm_cm),
			"sleep": cint(sleep),
			"energy": cint(energy),
		}
	)
	doc.save()
	return checkin_dict(doc)
