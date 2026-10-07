"""Load the shared library: program, exercises and seed foods from lift_log/data/*.json.

bench --site <site> execute lift_log.setup.seed.run

Idempotent: records are matched by program id, exercise name and (seed) food name, and only saved
when a value differs, so a second run changes nothing.
"""

import json
from pathlib import Path

import frappe
from frappe.utils import flt, getdate


def data_path(filename: str) -> Path:
	# Not get_app_path(..., filename): it scrubs hyphens out of the file name.
	return Path(frappe.get_app_path("lift_log", "data")) / filename


def read_json(filename: str):
	with open(data_path(filename), encoding="utf-8") as fh:
		return json.load(fh)


def run():
	summary = load()
	frappe.db.commit()
	print(json.dumps(summary, indent=1))
	return summary


def load() -> dict:
	program = read_json("program-block2.json")
	summary = {"program": {}, "exercises": {}, "foods": {}}

	_count(
		summary["program"],
		_upsert(
			"LL Program",
			{"program_id": program["id"]},
			{
				"program_id": program["id"],
				"program_name": program["name"],
				"start_date": program["start_date"],
				"end_date": program["end_date"],
				"definition": program,
			},
		),
	)
	for exercise in read_json("exercises.json"):
		_count(
			summary["exercises"],
			_upsert(
				"LL Exercise",
				{"exercise_name": exercise["name"]},
				{
					"exercise_name": exercise["name"],
					"exercise_type": exercise["type"],
					"increment_kg": exercise["increment_kg"],
					"form_url": exercise.get("form_url"),
				},
			),
		)
	for food in read_json("foods-seed.json"):
		_count(
			summary["foods"],
			_upsert(
				"LL Food Item",
				{"is_seed": 1, "food_name": food["food_name"]},
				{
					"food_name": food["food_name"],
					"portion": food["portion"],
					"kcal": food["kcal"],
					"protein_g": food["protein_g"],
					"is_seed": 1,
				},
			),
		)
	return summary


def _count(bucket: dict, outcome: str):
	bucket[outcome] = bucket.get(outcome, 0) + 1


def _same(stored, wanted) -> bool:
	if isinstance(wanted, dict | list):
		if isinstance(stored, str):
			stored = json.loads(stored or "null")
		return stored == wanted
	if isinstance(wanted, int | float):
		return flt(stored) == flt(wanted)
	if isinstance(wanted, str) and len(wanted) == 10 and wanted[4] == "-" and wanted[7] == "-":
		return stored is not None and getdate(stored) == getdate(wanted)
	return (stored or None) == (wanted or None)


def _upsert(doctype: str, filters: dict, values: dict) -> str:
	name = frappe.db.get_value(doctype, filters, "name")
	if not name:
		doc = frappe.get_doc({"doctype": doctype, **_serialise(values)})
		doc.insert(ignore_permissions=True)
		return "created"
	doc = frappe.get_doc(doctype, name)
	changed = {k: v for k, v in values.items() if not _same(doc.get(k), v)}
	if not changed:
		return "unchanged"
	doc.update(_serialise(changed))
	doc.save(ignore_permissions=True)
	return "updated"


def _serialise(values: dict) -> dict:
	return {k: json.dumps(v) if isinstance(v, dict | list) else v for k, v in values.items()}
