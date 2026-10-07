"""Program engine: week, phase and routine for a date, read from an LL Program's definition JSON."""

import json
from datetime import date, timedelta

import frappe
from frappe.utils import getdate

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def get_definition(program: str | None) -> dict | None:
	if not program:
		return None
	definition = frappe.get_cached_doc("LL Program", program).definition
	if isinstance(definition, str):
		definition = json.loads(definition or "null")
	return definition or None


def start_date(definition: dict) -> date:
	return getdate(definition["start_date"])


def week_count(definition: dict) -> int:
	return len(definition.get("weeks") or [])


def week_for(definition: dict, day: date) -> int | None:
	"""floor((date - start_date) / 7) + 1, or None outside the program."""
	week = (getdate(day) - start_date(definition)).days // 7 + 1
	return week if 1 <= week <= week_count(definition) else None


def week_entry(definition: dict, week: int | None) -> dict | None:
	if not week:
		return None
	for entry in definition.get("weeks") or []:
		if entry.get("week") == week:
			return entry
	return None


def phase_for(definition: dict, week: int | None) -> str | None:
	entry = week_entry(definition, week)
	return entry.get("phase") if entry else None


def routine_for(definition: dict, day: date) -> dict | None:
	"""The routine scheduled for a date: a training routine, a rest marker (Sunday check-in) or None."""
	day = getdate(day)
	entry = week_entry(definition, week_for(definition, day))
	if not entry:
		return None
	return (entry.get("days") or {}).get(WEEKDAYS[day.weekday()])


def is_training(routine: dict | None) -> bool:
	"""A routine that counts as a planned session. Rest days and empty optional days don't."""
	return bool(routine and not routine.get("rest") and routine.get("items"))


def week_dates(definition: dict, week: int) -> list[date]:
	monday = start_date(definition) + timedelta(days=7 * (week - 1))
	return [monday + timedelta(days=i) for i in range(7)]


def calendar_week(day: date) -> list[date]:
	"""Monday to Sunday around a date."""
	day = getdate(day)
	monday = day - timedelta(days=day.weekday())
	return [monday + timedelta(days=i) for i in range(7)]


def main_exercises(routine: dict | None) -> list[str]:
	return [item["exercise"] for item in (routine or {}).get("items") or [] if item.get("main")]
