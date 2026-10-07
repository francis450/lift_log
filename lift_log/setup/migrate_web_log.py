"""Move the old web log's export into Lift Log (docs/06).

bench --site <site> execute lift_log.setup.migrate_web_log.run \
	--kwargs "{'folder': '/path/to/data/export', 'user': '<login email>'}"

Idempotent:
- Sessions upsert by date, and never replace a session saved later than the export (e.g. one logged in the app).
- Food days merge by client_id: exported entries are upserted, entries added in the app are kept.
- Custom foods upsert by name. Entries with no kcal, protein or portion (a saved description, not a food) are skipped.
"""

import json
from pathlib import Path

import frappe
from frappe.utils import flt, get_datetime, getdate

from lift_log.api.utils import parse_utc
from lift_log.program import WEEKDAYS, get_definition, week_entry, week_for

PROGRAM_ID = "block-2-2026"
PROFILE_DEFAULTS = {
	"weight_kg": 72,
	"age": 25,
	"goal": "Lose fat, get stronger",
	"training_days": "mon,tue,wed,thu,fri",
	"session_time": "18:00:00",
	"time_zone": "Africa/Nairobi",
	"ai_enabled": 1,
}


def _read(path: Path) -> dict:
	with open(path, encoding="utf-8") as fh:
		raw = json.load(fh)
	# docs/06 describes a {id, data, version, updatedAt} wrapper; the actual export is unwrapped.
	return raw.get("data", raw) if isinstance(raw, dict) else raw


def run(folder: str, user: str) -> dict:
	summary = migrate(folder, user)
	frappe.db.commit()
	print(json.dumps(summary, indent=1))
	return summary


def migrate(folder: str, user: str) -> dict:
	root = Path(folder)
	if not root.is_dir():
		frappe.throw(f"Export folder not found: {folder}")
	if not frappe.db.exists("User", user):
		frappe.throw(f"User not found: {user}")

	summary = {
		"profile": ensure_profile(user),
		"sessions": {"saved": 0, "skipped_newer_in_app": 0},
		"sets": 0,
		"food_days": 0,
		"entries": 0,
		"custom_foods": {"saved": 0, "skipped": []},
	}
	for path in sorted((root / "sessions").glob("*.json")):
		sets = migrate_session(user, path.stem, _read(path))
		if sets is None:
			summary["sessions"]["skipped_newer_in_app"] += 1
		else:
			summary["sessions"]["saved"] += 1
			summary["sets"] += sets
	for path in sorted((root / "meals").glob("*.json")):
		summary["entries"] += migrate_food_day(user, path.stem, _read(path))
		summary["food_days"] += 1
	myfoods = root / "settings" / "myfoods.json"
	if myfoods.exists():
		for item in _read(myfoods).get("items", []):
			if migrate_custom_food(user, item):
				summary["custom_foods"]["saved"] += 1
			else:
				summary["custom_foods"]["skipped"].append(item.get("n"))
	return summary


def ensure_profile(user: str) -> str:
	if frappe.db.exists("LL Profile", user):
		return "exists"
	profile = frappe.get_doc({"doctype": "LL Profile", "user": user, "active_program": PROGRAM_ID, **PROFILE_DEFAULTS})
	profile.insert(ignore_permissions=True)
	return "created"


def _routine_key(day, routine_name: str | None) -> str | None:
	definition = get_definition(PROGRAM_ID)
	entry = week_entry(definition, week_for(definition, day)) if definition else None
	routine = (entry or {}).get("days", {}).get(WEEKDAYS[getdate(day).weekday()]) if entry else None
	if routine and routine.get("name") == routine_name:
		return routine.get("key")
	return None


def migrate_session(user: str, day: str, data: dict) -> int | None:
	"""Upsert one session. Returns the number of sets, or None when the app has a newer copy."""
	day = getdate(data.get("date") or day)
	saved_at = parse_utc(data.get("savedAt"))
	name = frappe.db.get_value("LL Workout Session", {"user": user, "session_date": day}, "name")
	if name:
		doc = frappe.get_doc("LL Workout Session", name)
		if doc.client_updated_at and saved_at and get_datetime(doc.client_updated_at) > saved_at:
			return None
	else:
		doc = frappe.new_doc("LL Workout Session")
		doc.user = user
		doc.session_date = day

	sets = []
	for exercise, rows in (data.get("sets") or {}).items():
		for i, row in enumerate(rows):
			kg = row.get("kg")
			sets.append(
				{
					"exercise": exercise,
					"set_no": i + 1,
					"kg": 0 if kg in (None, "") else flt(kg),
					"amount": flt(row.get("amt")),
					"effort": "",
					"done": 1,
				}
			)
	doc.update(
		{
			"program": PROGRAM_ID,
			"week": data.get("week"),
			"routine_name": data.get("routine"),
			"routine_key": _routine_key(day, data.get("routine")),
			"status": "done",
			"finished_at": saved_at,
			"note": data.get("note") or "",
			"client_updated_at": saved_at,
		}
	)
	doc.set("sets", sets)
	doc.save(ignore_permissions=True)
	return len(sets)


def migrate_food_day(user: str, day: str, data: dict) -> int:
	"""Merge exported entries into the day by client_id. Returns the number of exported entries."""
	day = getdate(data.get("date") or day)
	saved_at = parse_utc(data.get("savedAt"))
	name = frappe.db.get_value("LL Food Day", {"user": user, "food_date": day}, "name")
	doc = frappe.get_doc("LL Food Day", name) if name else frappe.new_doc("LL Food Day")
	if not name:
		doc.user = user
		doc.food_date = day

	exported = {}
	for item in data.get("items", []):
		exported[str(item["id"])] = {
			"client_id": str(item["id"]),
			"meal": str(item.get("meal") or "snacks").lower(),
			"food_name": item.get("n"),
			"portion": item.get("portion") or "",
			"qty": flt(item.get("qty")) or 1,
			"kcal_per_portion": flt(item.get("k")),
			"protein_per_portion": flt(item.get("p")),
			"source": "migrated",
			"added_at": saved_at,
		}
	kept = [row.as_dict() for row in doc.entries if row.client_id not in exported]
	doc.set("entries", [])
	for entry in [*exported.values(), *kept]:
		doc.append("entries", {k: entry.get(k) for k in exported_fields()})
	if not doc.client_updated_at or (saved_at and get_datetime(doc.client_updated_at) < saved_at):
		doc.client_updated_at = saved_at
	doc.save(ignore_permissions=True)
	return len(exported)


def exported_fields():
	return ("client_id", "meal", "food_name", "portion", "qty", "kcal_per_portion", "protein_per_portion", "source", "added_at")


def migrate_custom_food(user: str, item: dict) -> bool:
	name = (item.get("n") or "").strip()
	if not name or (not flt(item.get("k")) and not flt(item.get("p")) and not item.get("portion")):
		return False
	existing = frappe.db.get_value("LL Food Item", {"is_seed": 0, "user": user, "food_name": name}, "name")
	doc = frappe.get_doc("LL Food Item", existing) if existing else frappe.new_doc("LL Food Item")
	doc.update(
		{
			"food_name": name,
			"portion": item.get("portion") or "",
			"kcal": flt(item.get("k")),
			"protein_g": flt(item.get("p")),
			"is_seed": 0,
			"user": user,
		}
	)
	if not existing:
		doc.owner = user
	doc.save(ignore_permissions=True)
	return True
