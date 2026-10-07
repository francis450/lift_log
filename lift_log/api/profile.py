import json

import frappe

from lift_log.api.utils import DEFAULT_TZ, current_user, default_program, get_profile, profile_dict
from lift_log.targets import DEFAULT_KCAL

EDITABLE = (
	"weight_kg",
	"height_cm",
	"age",
	"goal",
	"kcal_target",
	"kcal_target_manual",
	"protein_target_g",
	"protein_target_manual",
	"targets_note",
	"session_time",
	"training_days",
	"time_zone",
	"active_program",
	"ai_enabled",
	"reminders",
)


@frappe.whitelist(methods=["GET"])
def get() -> dict:
	"""The profile plus the active program's definition. Before setup, the defaults with exists=false."""
	user = current_user()
	profile = get_profile(user)
	if profile:
		return {**profile_dict(profile), "exists": True}
	draft = _new_profile(user)
	draft.kcal_target = DEFAULT_KCAL
	return {**profile_dict(draft), "exists": False}


@frappe.whitelist(methods=["POST"])
def save(**fields) -> dict:
	"""Create or update the user's profile. Sending a target sets it to manual unless the same call
	sends its _manual flag; sending {"kcal_target_manual": 0} switches it back to automatic."""
	user = current_user()
	values = {k: v for k, v in fields.items() if k in EDITABLE}
	for target, flag in (("kcal_target", "kcal_target_manual"), ("protein_target_g", "protein_target_manual")):
		if target in values and flag not in values:
			values[flag] = 1
	if isinstance(values.get("reminders"), dict):
		values["reminders"] = json.dumps(values["reminders"])
	for numeric in ("weight_kg", "height_cm", "age", "kcal_target", "protein_target_g"):
		if numeric in values and values[numeric] in (None, ""):
			values[numeric] = 0

	profile = get_profile(user) or _new_profile(user)
	profile.update(values)
	profile.save()
	return {**profile_dict(profile), "exists": True}


def _new_profile(user: str):
	return frappe.get_doc(
		{
			"doctype": "LL Profile",
			"user": user,
			"goal": "Lose fat, get stronger",
			"session_time": "18:00:00",
			"training_days": "mon,tue,wed,thu,fri",
			"time_zone": DEFAULT_TZ,
			"active_program": default_program(),
			"ai_enabled": 1,
		}
	)
